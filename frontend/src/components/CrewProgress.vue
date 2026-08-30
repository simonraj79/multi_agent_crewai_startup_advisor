<script setup lang="ts">
/**
 * The crew, rowing the pipeline.
 *
 * Purpose, before aesthetics: this answers "how far along is the run, and what
 * is working right now" - two questions the graph could not answer, because at
 * its own default fit (scale 0.457) node titles render near 7px and the state
 * chip near 5px, and `running` and `completed` share an identical border
 * gradient. Colour on an illegible card is not a progress indicator.
 *
 * The three rowers are not decoration either. They are the three research
 * branches, and at the fan-out stage each oar strokes only while its own branch
 * is still working - so the picture shows the AND-join draining, which is the
 * one genuinely concurrent moment in the flow.
 *
 * Reduced motion is a first-class path, not an off switch: with animation
 * disabled this must still communicate sequence, so the boat stops stroking but
 * the numbered stepper, the checkmarks and the position all remain.
 */
import { computed } from 'vue'
import type { GraphDescriptor, NodeRunState } from '../types/studio'
import {
  CREW_STAGES,
  activeStageIndex,
  assertStageCoverage,
  stageProgress,
  type StageProgress,
} from '../data/crewStages'

const props = defineProps<{
  nodeStates: Record<string, NodeRunState>
  /** The topology on screen. The crew only rows a graph it knows. */
  descriptor: GraphDescriptor
  /** Suppresses the crew on an idle console - there is no voyage to draw yet. */
  active: boolean
}>()

/**
 * `CREW_STAGES` describes the validator pipeline specifically, but the run
 * composable is workflow-generic - `workflowId` is restored from localStorage
 * and could name `brief-flow`, whose seven nodes share not one id with the
 * stages. Every stage would then sit idle forever and the strip would announce
 * "Ready to launch - 0/7" across the top of a running graph.
 *
 * `assertStageCoverage` is the same check `crewStages.spec.ts` runs against the
 * live descriptor; using it here too is what makes its own docstring true, that
 * the runtime degrades rather than misinforming. An unknown topology gets no
 * crew, which is correct: there is no sequence here that this widget knows how
 * to narrate.
 */
const staged = computed(() => assertStageCoverage(props.descriptor).length === 0)

const progress = computed<StageProgress[]>(() => stageProgress(props.nodeStates, CREW_STAGES))
const activeIndex = computed(() => activeStageIndex(progress.value))
const visible = computed(() => staged.value && (props.active || activeIndex.value !== -1))

const completedCount = computed(() => progress.value.filter((p) => p.state === 'completed').length)

/** Left offset of the boat, as a percentage across the stage strip. */
const boatPercent = computed(() => {
  const total = progress.value.length
  if (total === 0) return 0
  const index = activeIndex.value === -1 ? 0 : activeIndex.value
  // Centre of the nth of `total` equal columns.
  return ((index + 0.5) / total) * 100
})

const current = computed(() => (activeIndex.value === -1 ? null : progress.value[activeIndex.value]))

/** Oars stroke only while the crew is actually pulling. */
const rowing = computed(() => current.value?.state === 'running')
const stalled = computed(() => current.value?.state === 'waiting')
const foundered = computed(() => current.value?.state === 'error')

/**
 * One oar per research branch. At the fan-out an oar rests as soon as its own
 * branch completes; elsewhere all three move together, because the crew is
 * pulling one task rather than three.
 */
const oars = computed(() => {
  const stage = current.value
  if (!stage) return [false, false, false]
  if (stage.stage.parallel) {
    return stage.stage.coreIds.map((id) => (props.nodeStates[id] ?? 'idle') === 'running')
  }
  return [rowing.value, rowing.value, rowing.value]
})

const headline = computed(() => {
  const stage = current.value
  if (!stage) return 'Ready to launch'
  if (stage.state === 'waiting') return `${stage.stage.label} - waiting for you`
  if (stage.state === 'error') return `${stage.stage.label} - failed`
  if (stage.stage.parallel && stage.state === 'running') {
    return `${stage.stage.label} - ${stage.done} of ${stage.total} branches home`
  }
  if (stage.state === 'completed') return `${stage.stage.label} - done`
  return stage.stage.label
})
</script>

<template>
  <div
    v-if="visible"
    class="crew-progress"
    :class="{ 'is-rowing': rowing, 'is-stalled': stalled, 'is-foundered': foundered }"
    role="group"
    :aria-label="`Pipeline progress: ${headline}. Stage ${activeIndex + 1} of ${progress.length}, ${completedCount} complete.`"
  >
    <div class="crew-head">
      <span class="crew-headline">{{ headline }}</span>
      <span class="crew-count">{{ completedCount }}/{{ progress.length }}</span>
    </div>

    <div class="crew-track">
      <!-- The river the crew rows along. -->
      <div class="crew-river" aria-hidden="true">
        <div class="crew-river-run" :style="{ width: `${boatPercent}%` }"></div>
      </div>

      <ol class="crew-stages">
        <li
          v-for="(entry, index) in progress"
          :key="entry.stage.id"
          class="crew-stage"
          :class="[`is-${entry.state}`, { 'is-current': index === activeIndex }]"
        >
          <span class="crew-marker" aria-hidden="true">
            <svg v-if="entry.state === 'completed'" viewBox="0 0 16 16" class="crew-tick">
              <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <template v-else>{{ index + 1 }}</template>
          </span>
          <span class="crew-label">{{ entry.stage.label }}</span>
          <span v-if="entry.stage.parallel" class="crew-branches" aria-hidden="true">
            <i v-for="n in entry.total" :key="n" :class="{ 'is-home': n <= entry.done }"></i>
          </span>
        </li>
      </ol>

      <!-- The crew. Three rowers, one per research branch. -->
      <div class="crew-boat" :style="{ left: `${boatPercent}%` }" aria-hidden="true">
        <svg viewBox="0 0 96 48" class="crew-boat-svg">
          <!-- Oars enter the water outboard of the hull, so the stroke reads as
               a stroke rather than as a wobbling line inside the boat. -->
          <g class="crew-oars" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" opacity="0.9">
            <line v-for="(pulling, i) in oars" :key="i"
                  class="crew-oar" :class="{ 'is-pulling': pulling }"
                  :style="{ animationDelay: `${i * 0.14}s` }"
                  :x1="30 + i * 17" y1="20" :x2="17 + i * 17" y2="38" />
          </g>
          <!-- Three rowers: one per research branch. -->
          <g class="crew-rowers" fill="currentColor">
            <g v-for="(pulling, i) in oars" :key="`r${i}`"
               class="crew-rower" :class="{ 'is-pulling': pulling }"
               :style="{ animationDelay: `${i * 0.14}s` }">
              <circle :cx="31 + i * 17" cy="10" r="4.4" />
              <path :d="`M${26.5 + i * 17} 26 q4.5 -10 9 0 z`" />
            </g>
          </g>
          <!-- Hull: a canoe with actual freeboard. A thinner lens vanished at
               this scale, which defeats the point of drawing a boat at all. -->
          <path class="crew-hull"
                d="M3 26 C 22 21, 74 21, 93 26 C 84 42, 12 42, 3 26 Z"
                fill="currentColor" />
          <path class="crew-gunwale" d="M3 26 C 22 21, 74 21, 93 26"
                fill="none" stroke="var(--bg-app)" stroke-width="1.6" opacity="0.55" />
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.crew-progress {
  position: absolute;
  z-index: 9;
  top: 64px;
  right: 40px;
  left: 40px;
  padding: 10px 16px 14px;
  background: rgba(26, 26, 26, 0.86);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
  -webkit-backdrop-filter: var(--blur-panel);
  backdrop-filter: var(--blur-panel);
  pointer-events: none;
}

.crew-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
.crew-headline { color: var(--text-title); font: 600 var(--fs-13)/1.3 var(--font-body); }
.crew-count { color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-mono); }
.crew-progress.is-stalled .crew-headline { color: var(--warn-text); }
.crew-progress.is-foundered .crew-headline { color: var(--err-text); }

/* Top padding reserves the lane the boat rows in. It must clear the stage
   markers completely - at 20px the hull sat on top of the number. */
.crew-track { position: relative; padding-top: 34px; }

.crew-river {
  position: absolute;
  top: 60px;
  right: 0;
  left: 0;
  height: 2px;
  overflow: hidden;
  background: var(--border-default);
  border-radius: 2px;
}
.crew-river-run { height: 100%; background: var(--gradient-brand); transition: width var(--motion-medium) var(--ease-out); }

.crew-stages { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; margin: 0; padding: 0; list-style: none; }
.crew-stage { display: flex; flex-direction: column; align-items: center; gap: 5px; }

.crew-marker {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  color: var(--text-40);
  font: 700 var(--fs-11)/1 var(--font-mono);
  background: var(--bg-node);
  border: 1px solid var(--border-default);
  border-radius: 50%;
  transition: color var(--motion-fast) ease, border-color var(--motion-fast) ease, background var(--motion-fast) ease;
}
.crew-tick { width: 13px; height: 13px; }

.crew-stage.is-completed .crew-marker { color: #101a18; background: var(--accent-mint); border-color: var(--accent-mint); }
.crew-stage.is-running .crew-marker { color: var(--accent-cyan); border-color: var(--accent-cyan); }
.crew-stage.is-waiting .crew-marker { color: var(--warn-text); background: var(--warn-bg); border-color: var(--warn-border); }
.crew-stage.is-error .crew-marker { color: var(--err-text); background: var(--err-bg); border-color: var(--err-border); }

.crew-label { color: var(--text-40); font: 600 var(--fs-11)/1 var(--font-mono); text-transform: uppercase; letter-spacing: 0.03em; }
.crew-stage.is-current .crew-label { color: var(--text-title); }
.crew-stage.is-completed .crew-label { color: var(--text-muted); }

.crew-branches { display: flex; gap: 3px; }
.crew-branches i { width: 5px; height: 5px; background: var(--border-hover); border-radius: 50%; }
.crew-branches i.is-home { background: var(--accent-mint); }

.crew-boat {
  position: absolute;
  top: 0;
  width: 66px;
  height: 33px;
  margin-left: -33px;
  color: var(--accent-cyan);
  transition: left var(--motion-medium) var(--ease-out);
}
.crew-progress.is-stalled .crew-boat { color: var(--warn-text); }
.crew-progress.is-foundered .crew-boat { color: var(--err-text); }
.crew-boat-svg { width: 100%; height: 100%; overflow: visible; }

/* A stroke, not a spin: catch, pull, recover. */
@keyframes oar-stroke {
  0%, 100% { transform: rotate(0deg); }
  40% { transform: rotate(26deg); }
  70% { transform: rotate(-8deg); }
}
@keyframes rower-pull {
  0%, 100% { transform: translateX(0); }
  40% { transform: translateX(-2.5px); }
}
@keyframes hull-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(1.5px); }
}

.crew-oar { transform-origin: center top; }
.crew-oar.is-pulling { animation: oar-stroke 1.05s ease-in-out infinite; }
.crew-rower.is-pulling { animation: rower-pull 1.05s ease-in-out infinite; }
.crew-progress.is-rowing .crew-hull { animation: hull-bob 2.1s ease-in-out infinite; }

/* A waiting crew has shipped its oars - the stillness is the signal. */
.crew-progress.is-stalled .crew-oar,
.crew-progress.is-stalled .crew-rower { animation: none; }

@media (prefers-reduced-motion: reduce) {
  /* Sequence must still be legible: the stepper, the ticks and the boat's
     position all survive. Only the stroke and the bob stop. */
  .crew-oar.is-pulling,
  .crew-rower.is-pulling,
  .crew-progress.is-rowing .crew-hull { animation: none; }
  .crew-boat, .crew-river-run { transition: none; }
}

@media (max-width: 1100px) {
  .crew-label { display: none; }
  .crew-progress { padding-bottom: 10px; }
}
</style>
