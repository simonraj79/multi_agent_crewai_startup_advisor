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
import { computed, ref, watch } from 'vue'
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
  /**
   * Node id -> how many times it has started. Optional so a caller that has not
   * wired it up degrades to "every stage is on lap 1" rather than breaking.
   */
  nodeVisits?: Record<string, number>
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

const progress = computed<StageProgress[]>(() =>
  stageProgress(props.nodeStates, CREW_STAGES, props.nodeVisits ?? {}),
)
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
 *
 * Each oar now carries its branch's NAME, which is the difference between "one
 * of three is still going" and "Signal is still going". The former is a
 * progress bar; only the latter tells an operator which tool to go and look at
 * when a run stalls.
 */
const oars = computed(() => {
  const stage = current.value
  if (!stage) {
    return [0, 1, 2].map((i) => ({ id: `idle-${i}`, label: '', pulling: false, state: 'idle' as NodeRunState }))
  }
  if (stage.stage.parallel) {
    return stage.branches.map((branch) => ({
      id: branch.id,
      label: branch.label,
      pulling: branch.state === 'running',
      state: branch.state,
    }))
  }
  // Off the fan-out the crew pulls one task together, so the three oars are the
  // same oar three times. They are still keyed on the stage so a re-render at a
  // stage change restarts the stroke rather than continuing mid-cycle.
  return [0, 1, 2].map((i) => ({
    id: `${stage.stage.id}-${i}`,
    label: '',
    pulling: rowing.value,
    state: stage.state === 'idle' ? ('idle' as NodeRunState) : (stage.state as NodeRunState),
  }))
})

/** Named oars, for the aria label and the caption row under the boat. */
const namedOars = computed(() => oars.value.filter((oar) => oar.label !== ''))

/** Which pass the crew is on. 1 is unremarkable and is never announced. */
const lap = computed(() => current.value?.lap ?? 0)
const looped = computed(() => lap.value > 1)

/**
 * The row-back is latched, and it keys on the LAP rather than on the boat's
 * position.
 *
 * Latched, because `activeIndex` settles within a frame and a class bound
 * straight to the transition would be gone before anyone read it. Six seconds
 * is long enough to notice and short enough not to bleed into the next stage.
 *
 * Keyed on the lap, because "the index went down" is a proxy and proxies drift.
 * It drifted here: answering a gate starts that stage's router, which briefly
 * re-opened the finished stage and moved the boat back one column, so the very
 * first live run announced a revision on a run that never revised. The stage's
 * lap climbing past 1 is the event itself and cannot mean anything else.
 */
const returning = ref(false)
let returnTimer = 0
watch(
  () => progress.value.map((entry) => entry.lap),
  (laps, previousLaps) => {
    if (!previousLaps) return
    const looped = laps.some((value, index) => value > 1 && value > (previousLaps[index] ?? 0))
    if (!looped) return
    returning.value = true
    window.clearTimeout(returnTimer)
    returnTimer = window.setTimeout(() => { returning.value = false }, 6000)
  },
)

/**
 * The message is about where the crew is NOW, so moving on retires it early.
 *
 * Without this the strip read "Review - waiting for you / SENT BACK FOR A
 * REVISION" at the verdict gate, two stages past the revision it was
 * describing - a true sentence attached to the wrong moment, which is the
 * failure mode a latch invites. The durable record of the loop is the stage's
 * own x2 badge; this line is the event, and an event stops being news.
 */
watch(activeIndex, (next, previous) => {
  if (previous === undefined || next <= previous) return
  window.clearTimeout(returnTimer)
  returning.value = false
})

/** Reset the latch on relaunch, so a new run never inherits the last one's. */
watch(
  () => props.active,
  (isActive) => {
    if (isActive) return
    window.clearTimeout(returnTimer)
    returning.value = false
  },
)

const headline = computed(() => {
  const stage = current.value
  if (!stage) return 'Ready to launch'
  const name = stage.stage.label
  if (stage.state === 'waiting') return `${name} - waiting for you`
  if (stage.state === 'error') return `${name} - failed`
  if (stage.stage.parallel && stage.state === 'running') {
    const pulling = stage.branches.filter((b) => b.state === 'running').map((b) => b.label)
    if (pulling.length > 0 && pulling.length < stage.total) {
      return `${name} - ${pulling.join(' + ')} still pulling`
    }
    return `${name} - ${stage.done} of ${stage.total} branches home`
  }
  if (stage.state === 'completed') return `${name} - done`
  return name
})

/**
 * Said beside the headline, not folded into it: the stage name answers "where
 * are we" and the lap answers "how did we get back here", and merging them
 * produces a sentence that changes shape between runs.
 */
const lapNote = computed(() => {
  if (returning.value) return 'sent back for a revision'
  if (looped.value) return `pass ${lap.value}`
  return ''
})

/**
 * The whole strip in one sentence, for a screen reader that gets none of the
 * picture. It has to carry the lap, because the row-back is exactly the event
 * a sighted operator sees and a listening one otherwise would not.
 */
const ariaSummary = computed(() => {
  const parts = [
    `Pipeline progress: ${headline.value}`,
    `Stage ${activeIndex.value + 1} of ${progress.value.length}`,
    `${completedCount.value} complete`,
  ]
  if (lapNote.value) parts.splice(1, 0, lapNote.value)
  return `${parts.join('. ')}.`
})
</script>

<template>
  <div
    v-if="visible"
    class="crew-progress"
    :class="{
      'is-rowing': rowing,
      'is-stalled': stalled,
      'is-foundered': foundered,
      'is-returning': returning,
      'is-looped': looped,
    }"
    role="group"
    :aria-label="ariaSummary"
  >
    <div class="crew-head">
      <span class="crew-headline">{{ headline }}</span>
      <span
        v-if="lapNote"
        class="crew-lap"
        data-testid="crew-lap"
        :class="{ 'is-fresh': returning }"
      >
        <svg viewBox="0 0 16 16" class="crew-lap-icon" aria-hidden="true">
          <path d="M13 6.5A5 5 0 1 0 13.5 10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          <path d="M13.2 2.6v4h-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        {{ lapNote }}
      </span>
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
          <!--
            One pip per branch, bound to THAT branch's own state rather than to
            a count of how many are home. The count version lit pips left to
            right regardless of which branch finished, so a fast Feasibility and
            a fast Market drew the same picture - and the picture was wrong.
          -->
          <span v-if="entry.stage.parallel" class="crew-branches" data-testid="crew-branch-pips">
            <i
              v-for="branch in entry.branches"
              :key="branch.id"
              :class="[`is-${branch.state}`]"
              :title="`${branch.label}: ${branch.state}`"
              :data-branch="branch.id"
            ></i>
          </span>
          <span
            v-if="entry.lap > 1"
            class="crew-stage-lap"
            data-testid="crew-stage-lap"
            :title="`${entry.stage.label} has run ${entry.lap} times`"
          >&times;{{ entry.lap }}</span>
        </li>
      </ol>

      <!-- The crew. Three rowers, one per research branch. -->
      <div class="crew-boat" :style="{ left: `${boatPercent}%` }" aria-hidden="true">
        <svg viewBox="0 0 96 48" class="crew-boat-svg">
          <!--
            Paint order is hull, then oars, then rowers, and it is load-bearing.
            Drawing the hull LAST buried every rower's torso under it, so the
            first live capture showed three disembodied heads floating over a
            yellow lens - a UFO, not a crew. Hull first means the rowers sit IN
            the boat, and the oars land between the two because an oar really
            does cross the gunwale between the rower's hands and the water.
          -->
          <path class="crew-hull" d="M3 27 C 10 24, 86 24, 93 27 L 89 36 C 82 42, 14 42, 7 36 Z" fill="currentColor" />
          <path class="crew-gunwale" d="M6 27.5 C 14 25.4, 82 25.4, 90 27.5"
                fill="none" stroke="var(--bg-app)" stroke-width="1.5" opacity="0.5" />

          <!--
            Every oar is drawn twice: a casing in the panel's own background
            colour, then the oar over it. Hull, oars and rowers are all
            `currentColor` - a single state colour is the point - so without the
            casing the oars simply dissolved into the hull they cross. The
            casing is a hole punched in the hull, which is also what an oarlock
            actually is.
          -->
          <g class="crew-oars">
            <g v-for="(oar, i) in oars" :key="oar.id"
               class="crew-oar" :class="[`is-${oar.state}`, { 'is-pulling': oar.pulling }]"
               :style="{ animationDelay: `${i * 0.14}s` }">
              <line class="crew-oar-casing" stroke="var(--bg-app)" stroke-width="5" stroke-linecap="round"
                    :x1="25 + i * 18" y1="21" :x2="13 + i * 18" y2="41" />
              <line stroke="currentColor" stroke-width="2.4" stroke-linecap="round"
                    :x1="25 + i * 18" y1="21" :x2="13 + i * 18" y2="41" />
            </g>
          </g>

          <!-- Three rowers: one per research branch. -->
          <g class="crew-rowers" fill="currentColor" stroke="var(--bg-app)" stroke-width="1.5">
            <g v-for="(oar, i) in oars" :key="`r${oar.id}`"
               class="crew-rower" :class="[`is-${oar.state}`, { 'is-pulling': oar.pulling }]"
               :style="{ animationDelay: `${i * 0.14}s` }">
              <circle :cx="27 + i * 18" cy="11" r="4.3" />
              <path :d="`M${22.4 + i * 18} 27 q0 -9 4.6 -9 q4.6 0 4.6 9 z`" />
            </g>
          </g>
        </svg>

        <!--
          Who is in the boat. Only drawn at the fan-out, because that is the one
          stage where the three rowers mean three different things; everywhere
          else they are one crew pulling one task and naming them would be a
          lie about the topology.
        -->
        <div v-if="namedOars.length" class="crew-oar-names" data-testid="crew-oar-names">
          <span
            v-for="oar in namedOars"
            :key="`n${oar.id}`"
            :class="[`is-${oar.state}`]"
            :data-branch="oar.id"
          >{{ oar.label }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/*
 * In the layout, not over it. `.graph-workspace` gives this its own grid row
 * (see studio.css) - as an overlay it sat on top of the Scoper card and the
 * scope gate, the two nodes it exists to narrate.
 *
 * `position: relative` still matters: the boat is absolutely positioned inside
 * `.crew-track` and needs a containing block that moves with the strip.
 */
.crew-progress {
  position: relative;
  z-index: 9;
  margin: 0 40px 4px;
  padding: 8px 16px 14px;
  background: rgba(26, 26, 26, 0.86);
  border: 1px solid var(--border-default);
  border-radius: var(--r-2xl);
  -webkit-backdrop-filter: var(--blur-panel);
  backdrop-filter: var(--blur-panel);
  pointer-events: none;
}

/* Three children now, and they are not equals: the headline and the lap chip
   are one phrase and belong together on the left, with the count pushed right
   by its own auto margin. `space-between` would have stranded the lap chip in
   the middle of the strip, reading as unrelated to the stage it describes. */
.crew-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.crew-headline {
  min-width: 0;
  overflow: hidden;
  color: var(--text-title);
  font: 600 var(--fs-13)/1.3 var(--font-body);
  white-space: nowrap;
  text-overflow: ellipsis;
}
.crew-count { margin-left: auto; color: var(--text-muted); font: 600 var(--fs-11)/1 var(--font-mono); }
.crew-progress.is-stalled .crew-headline { color: var(--warn-text); }
.crew-progress.is-foundered .crew-headline { color: var(--err-text); }

/* Top padding reserves the lane the boat rows in. It must clear the stage
   markers completely - at 20px the hull sat on top of the number. */
/*
 * The boat's lane, reserved at a FIXED height whether or not the oar captions
 * are showing. The strip is a real grid row now, so a strip that changed height
 * mid-run would resize the Vue Flow container under it and jolt the whole
 * graph - the captions therefore hang out of flow inside this padding rather
 * than adding to it. 46px is the boat (30) plus the caption line (16).
 */
.crew-track { position: relative; padding-top: 46px; }

.crew-river {
  position: absolute;
  top: 72px;
  right: 0;
  left: 0;
  height: 2px;
  overflow: hidden;
  background: var(--border-default);
  border-radius: 2px;
}
.crew-river-run { height: 100%; background: var(--gradient-brand); transition: width var(--motion-medium) var(--ease-out); }

.crew-stages { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; margin: 0; padding: 0; list-style: none; }
/*
 * `min-height` reserves the lane the branch pips and the lap badge appear in,
 * so the strip is the same height whether or not a run has looped. It is a real
 * grid row now, so a strip that grew mid-run would shrink the Vue Flow
 * container beneath it and shift the whole graph at the exact moment the
 * operator is reading it - the cost of a badge should be a badge, not a jolt.
 */
.crew-stage {
  display: flex;
  min-height: 62px;
  flex-direction: column;
  align-items: center;
  gap: 5px;
}

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

/* One pip per branch, coloured by that branch's own state. `running` gets the
   pulse so a stalled branch is distinguishable from a finished one at a glance
   - which is the whole reason the pips are per-branch now. */
.crew-branches { display: flex; gap: 3px; }
.crew-branches i {
  width: 5px;
  height: 5px;
  background: var(--border-hover);
  border-radius: 50%;
  transition: background var(--motion-fast) ease;
}
.crew-branches i.is-completed { background: var(--accent-mint); }
.crew-branches i.is-running { background: var(--accent-cyan); animation: pip-pulse 1.4s ease-in-out infinite; }
.crew-branches i.is-waiting { background: var(--warn-text); }
.crew-branches i.is-error { background: var(--err-text); }

@keyframes pip-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.45; transform: scale(0.8); }
}

/* The lap markers. Both are deliberately quiet until there IS a lap: a "x1" on
   every stage of every run would train the eye to ignore the one place the
   number matters. */
.crew-stage-lap {
  margin-top: 1px;
  padding: 0 4px;
  color: var(--warn-text);
  font: 700 var(--fs-11)/1.5 var(--font-mono);
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  border-radius: 999px;
}

.crew-lap {
  display: inline-flex;
  flex: 0 0 auto;
  gap: 4px;
  align-items: center;
  padding: 1px 8px 1px 6px;
  color: var(--warn-text);
  font: 600 var(--fs-11)/1.5 var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
  background: var(--warn-bg);
  border: 1px solid var(--warn-border);
  border-radius: 999px;
}
.crew-lap-icon { width: 12px; height: 12px; flex: 0 0 auto; }
/* The row-back is an event, not a state, so it announces itself once. */
.crew-lap.is-fresh { animation: lap-flash 1.1s ease-out 3; }

@keyframes lap-flash {
  0%, 100% { box-shadow: 0 0 0 0 rgba(0, 0, 0, 0); }
  35% { box-shadow: 0 0 0 4px var(--warn-bg); }
}

/* Names under the hull, so the three rowers stop being anonymous at the one
   stage where they are three different agents. */
.crew-oar-names {
  position: absolute;
  top: 30px;
  left: 50%;
  display: flex;
  justify-content: center;
  gap: 6px;
  white-space: nowrap;
  transform: translateX(-50%);
}
.crew-oar-names span {
  color: var(--text-40);
  font: 600 9px/1.2 var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  transition: color var(--motion-fast) ease;
}
.crew-oar-names span.is-running { color: var(--accent-cyan); }
.crew-oar-names span.is-completed { color: var(--accent-mint); }
.crew-oar-names span.is-error { color: var(--err-text); }

.crew-boat {
  position: absolute;
  top: 0;
  width: 68px;
  height: 30px;
  margin-left: -34px;
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

/*
 * Each oar pivots about its OWN oarlock.
 *
 * The default `transform-box: view-box` resolves `transform-origin` against the
 * whole SVG viewport, so `center top` put all three pivots on one point above
 * the boat and the oars swept like wipers instead of stroking. `fill-box` makes
 * the origin local to each line's own bounding box, and `top right` is the
 * handle end of a line that runs down-and-left into the water.
 */
.crew-oar { transform-box: fill-box; transform-origin: top right; }
.crew-oar.is-pulling { animation: oar-stroke 1.05s ease-in-out infinite; }
.crew-rower.is-pulling { animation: rower-pull 1.05s ease-in-out infinite; }
.crew-progress.is-rowing .crew-hull { animation: hull-bob 2.1s ease-in-out infinite; }

/*
 * The row-back.
 *
 * The boat's `left` transition already carries it to the earlier stage, but a
 * slide left and a slide right are the same gesture with the sign flipped, and
 * at 400ms nobody reads a sign. So the hull flips to face the way it is
 * travelling and the oars stroke in reverse: the crew is visibly backing water,
 * not drifting. That is what makes a revision look like a decision the operator
 * made rather than a glitch in the strip.
 */
.crew-progress.is-returning .crew-boat-svg { animation: boat-come-about 6s ease-in-out; }
.crew-progress.is-returning .crew-oar.is-pulling,
.crew-progress.is-returning .crew-rower.is-pulling { animation-direction: reverse; }

@keyframes boat-come-about {
  0% { transform: scaleX(1); }
  8%, 78% { transform: scaleX(-1); }
  100% { transform: scaleX(1); }
}

/* A waiting crew has shipped its oars - the stillness is the signal. */
.crew-progress.is-stalled .crew-oar,
.crew-progress.is-stalled .crew-rower { animation: none; }

@media (prefers-reduced-motion: reduce) {
  /* Sequence must still be legible: the stepper, the ticks and the boat's
     position all survive. Only the stroke and the bob stop. */
  .crew-oar.is-pulling,
  .crew-rower.is-pulling,
  .crew-progress.is-rowing .crew-hull,
  .crew-branches i.is-running,
  .crew-lap.is-fresh,
  .crew-progress.is-returning .crew-boat-svg { animation: none; }
  .crew-boat, .crew-river-run { transition: none; }
  /* The lap chip and the x2 badges are TEXT, so the loop survives the loss of
     every animation above. That is the property this block exists to keep:
     nothing here is the only carrier of a fact. */
}

@media (max-width: 1100px) {
  .crew-label { display: none; }
  .crew-progress { padding-bottom: 10px; }
}
</style>
