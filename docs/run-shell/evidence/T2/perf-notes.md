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
