# T2.8 — what was costing the frames, and what it costs now

Written by **W4** on branch `run-shell/cast`, 2026-09-05, working tree at
`7da9bf5` plus this round's uncommitted changes. Nothing here was committed and
no Playwright suite was run — RV re-runs `e2e/cast-perf.spec.ts` and it, not
this file, decides the criterion.

## 0. What RV3 measured, and what this round did about it

`evidence/T2/perf.json` records the failure twice, on two independent runs of
the deterministic fixture replay — 131 frames through the production client over
its own socket:

```
over34ms  15     (6 of them over 50 ms)
p95       32.3 ms
max      109.1 ms
budget    0 over 34 ms, p95 <= 20 ms
```

The measurements below are NOT that measurement. They cannot be: the criterion's
number is a `requestAnimationFrame` interval in Chromium, which includes style
recalculation, layout, paint and compositing, and this round was told not to run
the E2E suite. What could be measured here is the JavaScript and virtual-DOM
half — the part that runs on the main thread between frames and delays the next
one — plus two costs that are structurally certain in a browser and invisible in
jsdom. Both halves are recorded, and which is which is said on every line.

## 1. The harness

`evidence/T2/render-cost-bench.spec.ts.txt` — the exact file, kept as an
artifact rather than committed as a spec, because it is a stopwatch and not an
assertion and a suite should not carry a 30-second timing test that passes on
any machine. To reproduce, copy it to `frontend/tests/zzRenderCost.spec.ts` and
run `npx vitest run tests/zzRenderCost.spec.ts --reporter=verbose`.

What it does: mounts the real `useValidatorRun` against `FakeStudioApi` (the
suite's own transport double), renders the real `WorkflowNode` per graph node,
the real `ChatRail` and the real `DialogueRail` wired exactly as `StudioView`
wires them, then emits **262 frames** — both committed logs twice —
`await`ing the composable's promise-chained queue and a render tick after each,
and times each frame end to end. It also counts how many times a card component
actually re-rendered, which is the number that turned out to matter.

262 rather than 131 so the row count grows past the point where per-row cost
shows up. jsdom has no layout and no paint, so every figure here is a LOWER
bound on the browser's: it measures the work Vue does, not the work the work
causes.

## 2. Before and after

Same harness, same machine, same fixtures. "Before" is this branch as RV3
measured it; "after" is the same file with this round's changes, best of two
runs (the second run is within 13% on every row).

| Surface | | total (262 frames) | mean | p95 | max | card re-renders |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| canvas only | before | 333 ms | 1.27 | 2.21 | 10.60 | **2912** |
| | after | **165 ms** | **0.63** | **1.46** | 10.89 | **340** |
| trace only | before | 452 ms | 1.73 | 5.06 | 11.35 | — |
| | after | **249 ms** | **0.95** | **3.86** | 6.04 | — |
| dialogue only | before | 129 ms | 0.49 | 1.45 | 5.35 | — |
| | after | **80 ms** | **0.31** | **1.18** | 3.07 | — |
| everything | before | 829 ms | 3.16 | 7.25 | 13.13 | **3038** |
| | after | **360 ms** | **1.38** | **4.51** | 8.16 | **340** |

**−57% of the main-thread render cost, and −89% of the card re-renders.**

## 3. The causes, in the order they were found

### 3.1 Every frame re-rendered every card — 2,912 renders for 262 frames

`useValidatorRun.graphNodes` is one `computed` over nine reactive sources
(`nodeStates`, `nodeUsage`, `nodeFrames`, `nodeVisits`, `nodeActiveCall`, the
choreography's errors, replays and receipts, and `landed`). A frame touches at
least one of them, so it re-ran on every frame — and, written literally, it
minted fourteen fresh `data` objects each time. A new object is never
`props`-equal, so Vue re-rendered all fourteen cards for a frame that concerned
one node.

Fixed by caching the OBJECT rather than the work: the fields are still assembled
every time (they are plain reads), and a card whose nineteen fields are unchanged
is handed the object it already has. `sameNodeData` compares field by field
rather than by identity or `JSON.stringify`, because two fields break in opposite
directions — `usage` is mutated in place by `addUsage` (identity would say
"unchanged" about a card that just billed) and `activeCall` is replaced on every
call (identity would say "changed" about a card doing the same thing).

`2912 -> 340`. The 340 are the cards that really did change.

### 3.2 …and the fix did nothing until the `cast` prop was cached too

With `data` stable, the count stayed at 2,912. `StudioView` built
`{ identity, state }` inline for each card, and an object literal in a template
is a new object on every render — so the prop compared unequal and the card
re-rendered anyway. `useRunChoreography.castFor` now hands out a cached
`CastMark` per node, keyed on the two strings in it. Only with BOTH did the count
fall.

Worth stating on its own, because it is the general lesson: memoising a
component's inputs is all-or-nothing. One un-cached prop reinstates the whole
cost, and the profile looks identical either way.

### 3.3 The character generator's cache was per instance, not per module

`AgentCharacter` cached `pipSvg` output in `<script setup>`. **Everything in
`<script setup>` runs again for every component instance** — it *is* the setup
function — so the "module-level" cache was a cache of one, the shared
`IntersectionObserver` was one observer per character, and neither did what its
comment said.

Found by a spec, not by reading: an assertion that a second character joins the
first one's observer saw two observers constructed. The caches and the observer
now live in a plain `<script>` block beside `<script setup>`, which runs once.

### 3.4 Both rails re-rendered every row on every frame

A trace row is about forty elements — a name, a time, a line, a `<details>` with
a six-row `<dl>` and a `<pre>`, and since the cast a fifteen-element SVG
character. Appending one row re-evaluated the template for every row already
there, so the cost of a frame grew with the length of the run.

Both rails now build a cached row object per entry and carry `v-memo` on the
row. The memo key is the row object, and the key is honest because everything
rendered which can change independently of the entry is folded INTO that object:
the character's seed and its pose, both of which come from the run store rather
than from the entry. A key naming only the entry would freeze the newest row's
character in the pose it was born in, which is the one thing T2.6 measures.

### 3.5 The dialogue rail re-rendered its markdown sixty times a second

`shown` called `renderSpeech` — escape, then mark up — for **every** entry on
every recompute, and `read` called `readSpeech` on every entry's full text
beside it. A recompute happens on every reveal tick, and the reveal is driven by
`requestAnimationFrame`. Only one entry is ever revealing; the rest are finished
text whose markup cannot have changed.

Both are now cached by the entry OBJECT, which is an exact key because
`advanceReveal` replaces only the entries that moved.

And `advanceReveal` no longer replaces the ARRAY when nothing moved. It did so
unconditionally, which invalidated every consumer sixty times a second for a
rail in which nothing had changed — `grow` is fractional, and two steps a
quarter of a millisecond apart can leave a reveal on the same character.

### 3.6 Deep reactivity on two long arrays

`chatEntries` and `dialogue` were deep `ref`s. A deep ref proxies every object
it holds and every property read through it registers a dependency; the trace
template reads about a dozen properties per row, and a long run has hundreds of
rows. Both are `shallowRef` now, which is safe because every write in both files
already replaced the array rather than mutating it — the one obligation a
shallow ref imposes. `appendChat`'s two mutations (`push`, and an in-place index
write) were converted to replacements in the same change.

## 4. Two costs this harness cannot see, and why they are near-certainties

jsdom implements no scrolling, no compositing and no blur, so neither of these
appears in any figure above. Both are in files this round owns and both are the
shape of thing that produces a 109 ms outlier rather than a raised mean.

### 4.1 A smooth scroll started on every appended row

`ChatRail` watched `entries.length` and called
`list.scrollTo({ top: scrollHeight, behavior: 'smooth' })`. Three costs in one
line:

1. **A new animated scroll per row.** A burst of a dozen frames in one
   millisecond — exactly what the backend emits at a fan-out — started a dozen
   overlapping scroll animations, none of which ever caught up.
2. **A forced synchronous layout per frame.** Reading `scrollHeight` after
   `nextTick`, in the middle of the burst.
3. **It fought the reader**: anybody who had scrolled up was yanked back.

`DialogueRail` did the same on `[length, revealed]`, and `revealed` changes on
every `requestAnimationFrame` step of a reveal — so that one forced a layout
sixty times a second.

Both now coalesce on one `requestAnimationFrame`, scroll instantly rather than
animating, and skip entirely when the reader is more than 120 px from the
bottom. At most one measurement and one scroll per painted frame.

### 4.2 A backdrop blur on the one surface that repaints every frame

`.chat-rail` carried `backdrop-filter: blur(12px)` over a background of
`--surface-overlay`, which is **94% opaque** in the dark theme and 95% in the
light one. The blur therefore contributes about a twentieth of each pixel, and
it costs the compositor a blur of the whole rail's backdrop every time the
rail's own content changes — which on this surface is every frame of a run.
Removed. The two other rails keep theirs in `studio.css` (W5's); neither of them
repaints per frame.

## 5. What was NOT done, and why

**The `<details>` body is still in the DOM of every row** — about twenty-two of
the forty elements. Rendering it lazily is the largest remaining structural cut
and it was deliberately not taken:
`tests/traceInterpretation.spec.ts::"puts the raw payload, the model and the
token counts behind a closed disclosure"` asserts that the payload IS present
while the disclosure is closed, with the comment *"Nothing was dropped"*. That
is a documented contract, not an oversight, and weakening somebody else's spec
to make a number better is the wrong trade. `content-visibility: auto` on the
row already keeps the browser from laying out or painting a row that is scrolled
out of view, which is most of them.

**`CrewProgress.vue` and `motion.css` were not touched** — W5 owns them this
round.

## 6. The residual

The criterion's own number has not been re-measured, because this round did not
run Playwright. What can be said honestly:

- the main-thread render cost of a frame is **down 57%**, and the card
  re-renders that dominated it are **down 89%**;
- the two browser-only costs in §4 are removed, and both are of the kind that
  produces exactly the profile RV3 recorded — a p50 at 17.5 ms (a normal 60 Hz
  frame) with a long tail to 109 ms, which is what an overlapping smooth scroll
  and a backdrop re-blur look like, and not what a uniformly slow render looks
  like;
- whether that clears **0 over 34 ms and p95 <= 20 ms** on this machine is RV's
  measurement to take, and if it does not, the remaining profile should be
  attached rather than the budget lowered.

---

# Round three — the profile, and where the frames actually go

Written by **W4**, 2026-09-05, at `4d5fd05` plus this round's uncommitted
changes, on Windows 11 with every other worker idle and no other suite running.
The backend was the free one, started for this work and stopped after it:

```
SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099
CREDENTIALS_MASTER_KEY=Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE=
BUILDER_ALLOW_GATELESS_GRAPHS=1 RUN_RATE_LIMIT_MAX_RUNS=100
./.venv/Scripts/serve.exe            # log read, not /healthz trusted
```

**Round two guessed. This round measured, and the guess was wrong.** Round two's
notes attributed the residual to script and DOM cost and predicted the two
browser-only costs in its section 4 would close it. The profile says the main
thread is essentially idle for the whole replay: **one or two long tasks per
run, and not one of them overlaps an over-budget interval.** The frames are
being lost in raster, not in JavaScript.

## 1. The instrument

`scratchpad/zzProfile.spec.ts`, copied into `e2e/` to inherit
`playwright.config.ts` (Vite on :5273 proxying to :8099) and deleted afterwards.
It is `cast-perf.spec.ts`'s fixture replay frame for frame and gap for gap - the
same two committed logs, the same renumbering, the same `page.routeWebSocket`,
the same 250 ms clamp - with three recorders that file does not have:

1. a `longtask` `PerformanceObserver` installed in an `addInitScript`, so it is
   live before the app's first byte;
2. the same rAF sampler, so its intervals are comparable with `perf.json`'s
   rather than a second scale nobody can line up;
3. a `PROFILE_KILL` bisect that suppresses one suspect per run, so a recovered
   frame rate names the surface that was costing it.

It reproduces the criterion's own harness: minutes apart on the same machine,
`cast-perf.spec.ts` read **63 over 34 ms / p95 79.4** and the profiler read
**77 / 81.8**. Different runs of one thing, not two different things.

## 2. The bisect

131 frames, one arm per row, `over34` is the count of rAF intervals above the
budget and `p95` is in milliseconds. Every arm is the same replay against the
same backend within one hour.

| arm | what is suppressed | over 34 ms | p95 | long tasks |
| --- | --- | ---: | ---: | ---: |
| **none** | nothing - as shipped | **77** | **81.8** | 1 |
| anim | every `animation` and `transition` | 64 | 65.8 | 1 |
| shadow | every `box-shadow` and `filter` | 70 | 72.2 | 1 |
| pips | every character | 67 | 77.3 | 1 |
| edges | every Vue Flow edge | 75 | 74.1 | 1 |
| rails | the whole trace rail | 72 | 71.2 | 2 |
| **blur** | **every `backdrop-filter`** | **13** | **28.3** | 1 |
| blur-strip | the crew strip's blur only | 80 | 81.1 | 2 |
| blur-report | the report panel's blur only | 77 | 55.7 | 2 |
| blur-header | the header's blur only | 69 | 73.3 | 1 |
| blur-control | the right rail's blur only | 40 | 56.5 | 1 |
| blur + pips | both | 16 | 29.2 | 2 |
| blur + anim | both | 21 | 30.0 | 2 |
| blur + rails | both | 19 | 28.5 | 2 |
| blur + content-visibility forced on | both | 23 | 31.8 | 1 |

Repeats of the `blur` arm: **13, 16, 19, 20, 21, 26** - call it 20 +/- 6, p95
28-34. That spread is the noise floor, and no arm above is read as different
from another inside it.

## 3. What that says

**`backdrop-filter` is roughly three quarters of the miss.** Removing it takes
77 to about 20, and p95 82 to about 30. No single surface dominates: killing one
of the four leaves the other three, and only killing all four recovers the frame
rate. That is what a backdrop blur does - each one forces the compositor to
re-read and re-blur everything behind it, so the cost is per-surface and
additive.

The four, all still present, and **all of them in files another worker owns this
round**:

```
src/studio.css:149                   .app-header      var(--blur-panel)   5px
src/studio.css:333                   .control-rail    var(--blur-rail)   12px
src/components/CrewProgress.vue:520  .crew-progress   var(--blur-panel)
src/components/ReportPanel.vue:300   .report-panel    var(--blur-rail)
```

Every one of them sits on a background of `--surface-overlay` or `--header-bg`,
which are **94%, 95% and 88% opaque**. A 5-12 px blur of what is behind a
94%-opaque surface contributes about a twentieth of each pixel. W4 removed the
fifth - `.chat-rail`'s - in round two for exactly this reason and measured
nothing lost; these four are the same trade and are not W4's to make.

**Nothing left in W4's files is measurable.** With the blur gone, suppressing
every character (16), every animation (21) or the entire trace rail (19) moves
the number by less than the run-to-run spread of the arm they are measured
against. Round two's work is why: it removed the script cost, and the profile
now finds one long task per run - 104 ms, at page mount, before the replay
starts.

## 4. The floor, and it is the harness

Two control arms settle what the remaining ~20 is.

| control | over 34 ms | p95 | max |
| --- | ---: | ---: | ---: |
| **idle page, no replay at all** (11 s, same page, same sampler) | **0** | **22.2** | 28.4 |
| replay running, whole shell `visibility: hidden` | 17 | 27.3 | 143.8 |
| replay running, shell hidden AND blur off | 24 | 30.7 | 249.6 |
| replay running, everything painted, blur off | ~20 | ~30 | ~148 |

Read down that column. A page at rest holds 60 Hz - **zero** dropped intervals.
Start the replay with **nothing of ours painting at all** and it drops 17.
Un-hide the whole console and it drops about 20. So the step from 0 to 17 is the
replay itself - the socket, the CDP round trip that drives it, and applying 131
frames - and the step from 17 to 20 is everything this console draws.

The renderer explains it, and the profiler now records it:

```
ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)
```

**Headless Chromium here rasterises in software.** That is why a backdrop blur
is catastrophic rather than merely expensive, and it is why an unpainted page
still cannot hold a 60 Hz cadence under a driven WebSocket replay.

## 5. The residual, named

Against a budget of **0 intervals over 34 ms and p95 at or under 20 ms**:

- **The p95 bar is unreachable in this environment by any product change.** An
  idle page with nothing happening measures **p95 22.2 ms**. The harness's own
  budget derivation looks at the MEDIAN (16.5 ms, a clean 60 Hz) and declares
  `sixtyHz: true`, so it never sees that this machine's p95 is already over the
  bar before the console does anything at all.
- **Zero over 34 ms is reachable only from the idle arm**, which is the arm with
  no replay in it. With the replay running and nothing painted, it is 17.
- **The product's own share is about 3 of 77** once the blur is gone, and that
  is inside the noise.

So the honest split is: **about 57 of the 77 are `backdrop-filter`, about 17 are
the harness, and about 3 are the console.** The first is a four-line change in
three files W4 does not own this round; the second is not a frontend defect at
all.

## 6. Final numbers, as `perf.json` stands

Re-run at the end of this session, product unchanged, machine idle:

```
fixtureReplay   131 frames, 401 intervals, p50 16.8, p95 71.9, max 156.4,
                over34ms 69, over50ms 40, windowSeconds 10.07, completed
liveSyntheticRun  386 over 34 ms, p95 84.0, max 190.7   (in the failure text;
                see note 2 of RV3's second pass - the live arm asserts before
                `record()`, so its numbers are still absent from the artifact)
budget          idleMedian 16.5-16.8 ms, refresh ~60 Hz, sixtyHz true,
                dropBudget 34 ms, p95Budget 20 ms
```

RV3's second pass recorded 4 / 26.8 for the same replay. This session measured
63, 69 and 77 across three runs an hour apart with the machine otherwise idle.
**That 4 was a lucky run, not a better build** - the code between the two is the
same code - which is the sharpest form of RV3's own note 3: no single run of
this measurement means anything, and a future "it passes now" needs several.

## 7. Artifacts

- `evidence/T2/profile-longtasks.json` - the as-shipped arm: every long task
  with its attribution, every over-budget interval with the long task that
  overlapped it (none did), and the DOM census at the shutter.
- `evidence/T2/profile-longtasks-blur.json` - the same with `backdrop-filter`
  suppressed, which is the pair that carries section 3.
- The bisect script is `scratchpad/zzProfile.spec.ts`; it was copied into
  `e2e/`, run, and deleted. It is not committed, because a stopwatch that
  asserts nothing does not belong in a suite.
