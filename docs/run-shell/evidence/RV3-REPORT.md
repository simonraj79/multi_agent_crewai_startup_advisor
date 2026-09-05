# RV3 — verification report

Six passes. **The sixth, at `2cea4b9`, is the current verdict**; the five before
it are kept below under their own headings, because what each round fixed is
only legible against what the previous pass found.

RV3 built none of this work and edited no product code. The one product-tree
change RV3 is permitted is regenerating the PNGs under
`frontend/e2e/visual/run-canvas.spec.ts-snapshots/` — two in the first pass, one
in the second, all three in the third and again in the fourth, and **none in the
fifth or sixth**, each named with a reason in
[`evidence/R/baselines.md`](R/baselines.md).

`G1`, `G4`'s sheet and every `RC` row belong to other workers and are marked
**NOT VERIFIED BY ME**. A missing artifact is recorded as **FAIL**, not as a
pass with a note.

---

# SIXTH PASS — `2cea4b9`, 2026-09-05 (targeted)

A **targeted** re-run of the surfaces round seven touched. The full Playwright
suite was last run at `8ae40ec` (163 tests, 160 passed, 3 failed, 0 skipped,
12.8 m) and R1 cites it explicitly rather than pretending to a sweep.

The branch head is `a182ed6`, a docs-only commit on top of `2cea4b9`; the product
source is identical at both. Round seven is eight frontend files — `tokens.css`,
`DialogueRail.vue`, `ReportPanel.vue`, `StatusPanel.vue`, `useRunChoreography.ts`,
`runStatusDisplay.ts`, `studio.css`, `StudioView.vue`. No Python.

Before anything ran: every listener on 5273 / 5274 / 5275 / 8099 / 8791 was
hunted and none existed, and all five answered nothing — so Playwright started
its own Vite from this tree and `reuseExistingServer` had nothing to reuse.

## 1. What was run, and what it said

| | |
| --- | --- |
| `e2e/visual/run-canvas.spec.ts` | **3/3 passed, 22.0 s, NO regeneration** — md5s unchanged |
| `e2e/visual/builder-canvas.spec.ts` | **16/16 passed, 41.7 s, no regeneration** |
| `e2e/cast.spec.ts` + `e2e/studio.spec.ts` | **17/17 passed, 2.9 m** — rewrote every capture |
| `e2e/cast-perf.spec.ts` alone | **1 passed, 1 failed** — T2.8, by one drop at the median |
| Vitest | **93 files, 2007 tests, 0 failed**, exit 0 |
| Types | `npx vue-tsc -b --force` — **exit 0** |
| Build | `npm run build` — **exit 0**, built in 709 ms |
| Contrast | `node scripts/contrast-audit.mjs` — **exit 0**, 236 pairings, 234 in scope, **0 failing** |

Backend: the usual `SYNTHETIC=1` line on :8099 with the six-mode
`SYNTHETIC_FAILURE`; it survived the whole pass. Money spent: **zero**.

## 2. T2.8 — the arms

| arm | samples (over 34 ms) | median over 34 ms | median p95 | median max | intervals |
| --- | --- | ---: | ---: | ---: | ---: |
| **idle** | — (single) | **0** | 17.8 | 20.0 | 601 |
| **hidden** | 4, 4, 3 | **4** | 18.3 | 80.8 | 554 |
| **painted** | 5, 6, 4 | **5** | 18.4 | 78.0 | 549 |

**`addedDrops = 1`, `p95Delta = 0.1 ms` against 4 ms of headroom,
`passes: false` — FAIL.** Live arm, recorded and not graded: 152 frames,
p50 16.7, p95 18.2, max 81.5, 3 over 34 ms.

**Seven measurements of this comparison across four commits:**

| commit | context | hidden median | painted median | addedDrops | |
| --- | --- | ---: | ---: | ---: | :-: |
| `601baef` | alone | 4 | 5 | 1 | FAIL |
| `8ae40ec` | alone (1st) | 3 | 3 | **0** | PASS |
| `8ae40ec` | full suite | 3 | 4 | 1 | FAIL |
| `8ae40ec` | alone (2nd) | 6 | 7 | 1 | FAIL |
| `c2966e7` | alone | 4 | 4 | **0** | PASS |
| **`2cea4b9`** | **alone** | **4** | **5** | **1** | **FAIL** |

Two of seven pass. The p95 arm has passed **every single time** (0.0–0.1 ms
against 4 ms), and the painted arm's absolute p95 has been 18.1–18.4 ms in all
of them, inside the retired ≤ 20 ms bar. The drop arm is a coin-flip on a
one-frame difference while the control's own median has ranged 3 to 6.

RV3's reading, unchanged from the fourth pass and now with three more samples:
**the console's cost is at or below the instrument's noise floor**, and the
criterion as written resolves that to FAIL more often than not. That is a fact
about a one-frame threshold, not about the console — but the criterion is the
criterion, so T2.8 is **FAIL** on this pass's measurement.

## 3. The six captures, looked at

**`S/empty.png` — the rest-state word is `Ready`, in all three places.** The
header connection chip, the canvas heading and the status rail all read `Ready`,
and the line beneath reads `ready · seq 0 · 0 dropped`. That is
`runStatusDisplay` doing what it was added for; earlier passes had the header
saying `Connected` at rest while the canvas said something else. ELAPSED `00:00`,
Launch enabled, every node idle with its character, the trace rail saying "Run
activity will appear here."

**`T3/after-1440.png` — the Score breakdown table's rows are visible under
SCORES.** `DIMENSION / SCORE / WEIGHT / NOTE` with Demand 3 · 0.30, Market
3 · 0.20, Competitive room 3 · 0.20 all legible. In every earlier pass the
sticky `2 CITED SOURCES` footer sat over exactly this table; the sources are now
a block inside the report's one scroller and the table is readable. ELAPSED
reads `00:30`.

**`T2/reduced-motion.png` — ELAPSED `00:14`, non-zero.** Status `Running`, the
canvas heading `Running`, the Launch control `Running…`. The dialogue drawer
holds one entry and shows it **whole, ending "…with the shape of a real one."
with its `› Details` toggle beneath it**.

**`S/failure.png` — ELAPSED is `00:00`, and the canvas heading now says
`Failed`.** The zero is the one thing the orchestrator asked me to check for a
non-zero value, so it is worth being exact: this run started and failed inside
the same second (CALLS 1, TOKENS 550, and the synthetic refusal fires on the
first attempt), so `00:00` is an honest reading of a sub-second run rather than
a stopped clock. The clock's realness is demonstrated by the other two captures
(`00:14` and `00:30`), not by this one. The canvas heading reading `Failed`
rather than `Error` is `runStatusDisplay` again, matching the status rail.

**`S/narrow-rail-open.png` — the dimming reads now.** Measured at the element
rather than judged by eye: exactly one `.rail-scrim`, computed
`background-color: rgba(10, 10, 10, 0.72)`, `backdrop-filter: none`,
`scrollWidth = 390` with the rail open. The strip of shell left visible beside
the overlay is clearly a layer behind glass rather than a competing surface,
which `.58` did not achieve. `tokens.css:297-309` records that judgement and the
two cold reads behind it.

**`T2/trace-completed.png` and `S/long-run.png` — the dialogue did NOT land at
its end, and this is the one thing this pass did not confirm.** Both captures
show the drawer's newest visible entry, the Synthesist's, **cut mid-sentence** at
"…and I am", with its `› Details` toggle clipped by the drawer's bottom edge, and
the drawer's own badge reading **8** while six entries are shown.

RV3 measured it rather than leaving it to the eye. A throwaway spec drove a run
to completion and read the dialogue scroller 2.5 s after the terminal frame:

```
selector        [role="log"]        (inside region "Agent dialogue")
scrollTop       23
scrollHeight    739
clientHeight    360
distance to end 356 px
entries         6
last entry bottom 843   scroller bottom 509   lastFullyVisible: false
```

The list is **23 px from the top and 356 px from the end**. Whatever the landing
is meant to fire on, it had not fired in that state, and the two committed
captures agree with the measurement. This is reported as an observation, not as
a criterion failure: no DoD row asks the dialogue to land at its end, and every
S and T2 row that does rest on the trace rail passes. But the round's own stated
change is not visible in the evidence it produced.

*(One caveat RV3 will not hide: the throwaway drove the ordinary two-gate journey,
not `cast.spec.ts:1183`'s 119-event journey with three revise turns. The two
committed captures come from that longer journey and show the same thing, so this
is two observations of one behaviour rather than one.)*

## 4. The table

Rows this pass re-measured are marked *(re-run)*. Every other row **carries its
fifth-pass verdict unchanged** and says so — round seven touched eight frontend
files and no test, fixture or Python.

| Id | Verdict | Evidence | What RV3 saw at `2cea4b9` |
| --- | :---: | --- | --- |
| **G1** | NOT VERIFIED BY ME | `evidence/G1/` | RV2's. Untouched in all six passes. |
| **G2** | **PASS** *(re-run)* | `G2/grep.txt` | **1 hit, 0 product hits** — the `readsAsRole()` JSDoc example at `:138`. Round seven's own risk to this row was `runStatusDisplay`, a new module mapping a run STATE to one word: a state is not a role, and the module is not in the grep's paths. |
| **G3** | **PASS** *(re-run)* | `G3/vitest.txt`, `G3/playwright.txt` | `cast.spec.ts:998`'s reload check green (15.6 s). |
| **G4** | NOT VERIFIED BY ME | `G4/roles-sheet.png` | RC's Q4. |
| **T1.1** | NOT VERIFIED BY ME | both report headers, `T1/cold-read.md`, `RC/answers.md` | `cast.spec.ts:1682` green; both headers rewritten. A third cold read landed in `a182ed6` — RV3 does not grade it. |
| **T1.2** | **PASS** *(re-run)* | `T1/vitest.txt`, `T3/after-1440.png` | Unit green, and the score breakdown is now readable under SCORES: every dimension in words, `thin` chips, weights and notes. |
| **T1.3** | **PASS** *(re-run)* | `S/failure.png`, `R/playwright.txt` | `cast.spec.ts:2095` green; the node card's error stays humanised (`Synthetic failure:`, not `SYNTHETIC_FAILURE:`). |
| **T1.4** | **PASS** *(carried, pass 5)* | `T1/vitest.txt` | Green inside 2007/2007. |
| **T1.5** | **PASS** *(re-run)* | `T1/data-layer-diff.txt` | All three diffs **empty**, `config.py` untouched. Six passes, six empty answers. |
| **T2.1** | **PASS** *(re-run)* | `T2/trace-completed.png`, `T2/interpretation-vitest.txt` | `cast.spec.ts:1183` green in a browser. The dialogue-landing observation in section 3 is about the *dialogue drawer*, which is a separate surface from the trace rows this row is about. |
| **T2.2** | **PASS** *(carried, pass 5)* | `T2/vocabulary.md` | `interpret.ts` unchanged this round; the serializer's ladder has never changed on this branch. |
| **T2.3** | NOT VERIFIED BY ME | `T2/characters-32px.png`, `T2/states-32px.png` | RC's Q4. |
| **T2.4** | **PASS** *(carried, pass 5)* | `CHARACTERS.md` | `pip.ts` unchanged this round. |
| **T2.5** | **PASS** *(re-run — and this is the row round seven put at risk)* | `T2/no-timers.txt` | Round seven made ELAPSED **a real ticking clock**, so the question was where the `setInterval` landed. It is `StatusPanel.vue:211/234` — a panel of numbers in the control rail, driving one readout and no `data-state`. The criterion's own grep still returns **exactly the same three hits** in `useRunChoreography.ts` (`:259`, `:290`, `:826`), and `frontend/src/characters/` + `AgentCharacter.vue` return **zero** for all five clock routes, now with a ticking clock in the same application. |
| **T2.6** | **PASS** *(re-run)* | `T2/tie-in.png` | `cast.spec.ts:907` green (2.9 s). |
| **T2.7** | **PASS** *(re-run)* | `T2/reduced-motion.png` | `:1062` and `:1101` green. |
| **T2.8** | **FAIL** *(re-run)* | `T2/perf.json` | Section 2. `addedDrops = 1`, `p95Delta = 0.1`, `passes: false`. |
| **T2.9** | **PASS** *(carried, pass 5)* | `T2/rowers-grep.txt`, `T2/node-running.png` | `WorkflowNode.vue` unchanged this round; `node-running.png` re-captured anyway and the three rower classes still return zero across `frontend/src`. |
| **T3.1** | **PASS** *(re-run)* | `T3/scope-order.txt` | Sixteen minutes fifty seconds; six rounds of `studio.css` edits cannot alter the order of the first two commits. |
| **T3.2** | **PASS** *(re-run)* | `T3/literals.txt` | `designTokens.spec.ts` green inside 2007/2007, after a round that moved `--scrim` twice and added `runStatusDisplay` colours. |
| **T3.3** | **PASS** *(re-run)* | `T3/contrast.md`, `T3/contrast-rv3-rerun.txt` | **exit 0**, 236 pairings, 234 in scope, **0 failing**, byte-identical to the committed file. `--scrim` moved and the count did not, which RV3 checked rather than took from the comment: `grep -c scrim contrast.md` returns **0**, so the scrim really is in no pairing. |
| **T3.4** | **PASS** *(re-run)* | all `before-*` and `after-*` | All four rewritten and looked at; `after-1440.png` is the one that improved. |
| **T3.5** | **PASS** *(re-run)* | `T3/builder-visual.txt` | **16/16 green, no regeneration**, md5s identical. Six passes, six greens. |
| **S1** | **PASS** *(re-run)* | `S/empty.png` | Section 3 — the rest state reads `Ready` everywhere. |
| **S2** | **PASS** *(re-run)* | `S/first-run.png` | `cast.spec.ts:764` green (18.2 s). |
| **S3** | **PASS** *(re-run)* | `S/long-run.png`, `S/long-run.md` | `:1183` green. The newest **trace** row is visible at the bottom; the dialogue-drawer observation is section 3. |
| **S4** | **PASS** *(re-run)* | `S/failure.png` | `:2095` green; one banner, `Failed` in both places, humanised error. |
| **S5** | **PASS** *(re-run)* | `T2/reduced-motion.png` | Written by the passing `:1101`. |
| **S6** | **PASS** *(re-run)* | `S/narrow.png`, `S/narrow-rail-open.png` | `:1867` green; the scrim measured at `.72` with no blur and `scrollWidth = 390`. |
| **R1** | **FAIL** | `R/*` | **Targeted pass.** Cited from `8ae40ec`: **163 tests, 160 passed, 3 failed, 0 skipped, 12.8 m**. Measured here at `2cea4b9`: **37 of 38 Playwright tests green across four specs** (the one red is T2.8), **2007 Vitest**, `vue-tsc` 0, `npm run build` 0, contrast 0. The full suite's other two reds are the builder drag pair — `:1227` proved pre-existing on `main`, `:1552` passes alone. |
| **R2** | **PASS** *(re-run)* | `R/diff-stat.txt` | Four forbidden surfaces each **NO DIFF**; `git diff 16f3be5..HEAD -- src/` **empty** — no `src/brief_crew` file has changed in seven rounds. |

## 5. Things a reader should know that no criterion asks for

1. **The dialogue drawer does not land on its newest entry.** Section 3, with the
   scroll measurement. No DoD row requires it; the round said it did it; the
   evidence says otherwise. Worth one look before the verdict table is signed.
2. **`S/failure.png`'s ELAPSED is `00:00`** and that is honest — the run failed
   inside a second. The ticking clock is demonstrated by `00:14` and `00:30` in
   the other two captures.
3. **The Python suite was not re-run** and does not need to be: no Python
   changed, which `R/diff-stat.txt` proves with an empty
   `git diff 16f3be5..HEAD -- src/`. `R/python.txt` carries the fourth pass's
   **2544 / OK / 6 skipped** and says so at the top.
4. **`builder.spec.ts:1227` is pre-existing and measured** —
   `evidence/R/builder-1227.md`, HEAD 0/5 against `main` 1/5 with an identical
   call log. It should be split out of remaining-work item 44.
5. **Two artifacts still predate the character they show**: `G4/roles-sheet.png`,
   `T2/characters-32px.png` and `T2/states-32px.png` were last written before the
   bun crest. G4 and T2.3 turn on a reader looking at those.
6. **Tally: 25 PASS, 2 FAIL, 4 NOT VERIFIED BY ME** over the 31 rows.
   Pass 5 was 26 / 1 / 4; pass 4 was 25 / 2 / 4; pass 3, 25 / 2 / 4; pass 2,
   22 / 5 / 4; pass 1, 19 / 8 / 4. The two FAILs are **T2.8**, which has passed
   twice and failed five times on a one-frame threshold, and **R1**, whose
   remaining reds are T2.8 plus one test proved pre-existing on `main` and one
   that passes alone.

---
---

# FIFTH PASS — `c2966e7`, 2026-09-05 (targeted)

A **targeted** re-run of the surfaces round six touched, not a full sweep. The
full Playwright suite was last run at `8ae40ec` (163 tests, 160 passed, 3 failed,
0 skipped, 12.8 m) and R1 below cites it explicitly rather than pretending
otherwise.

Round six is five files: `ReportPanel.vue`, `WorkflowNode.vue`,
`useRunChoreography.ts`, `studio.css` (+46, the new `--rail-cover-*` variables)
and `interpret.ts` (+27, the error humaniser). No Python.

## 0. No stale dev server, checked before anything ran

`playwright.config.ts` sets `reuseExistingServer: true`, so a Vite left over
from an earlier session would serve an older bundle to every capture and nothing
would say so.

```
listeners on 5273 / 5274 / 5275 / 8099 / 8791   -> all free, none to stop
GET http://127.0.0.1:{5273,5274,5275,8099,8791} -> no answer, all five
```

## 1. What was run, and what it said

| | |
| --- | --- |
| `e2e/visual/run-canvas.spec.ts` | **3/3 passed, 21.9 s, NO regeneration** — the three baselines are byte-for-byte the fourth pass's |
| `e2e/visual/builder-canvas.spec.ts` | **16/16 passed, 41.1 s, no regeneration** — md5s identical before and after |
| `e2e/cast.spec.ts` + `e2e/studio.spec.ts` | **17/17 passed, 2.9 m** — rewrote every T1/T2/T3/S capture |
| `e2e/cast-perf.spec.ts` alone | **2/2 passed** — T2.8's graded comparison passes |
| Vitest | **93 files, 1987 tests, 0 failed**, exit 0 |
| Types | `npx vue-tsc -b --force` — **exit 0** |
| Build | `npm run build` — **exit 0**, built in 614 ms |
| Contrast | `node scripts/contrast-audit.mjs` — **exit 0**, 236 pairings, 234 in scope, **0 failing** |

Backend: `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099` with
`CREDENTIALS_MASTER_KEY`, `BUILDER_ALLOW_GATELESS_GRAPHS=1`,
`RUN_RATE_LIMIT_MAX_RUNS=100`, `MCP_ALLOW_INSECURE_LOCAL=1`, `SKILLS_ROOT` and
the six-mode `SYNTHETIC_FAILURE`. It survived the whole pass this time
(`/healthz` 200 after the cast run). Money spent: **zero**.

## 2. T2.8 — PASSES, and here is every arm and every sample

`over34ms(painted) ≤ over34ms(hidden)` on the **median** of six alternating arms,
and `p95(painted) ≤ p95(hidden) + 4 ms`. From `evidence/T2/perf.json`:

| arm | samples (over 34 ms) | median over 34 ms | median p95 | median max | intervals |
| --- | --- | ---: | ---: | ---: | ---: |
| **idle** — page at rest | — (single, 600 intervals) | **0** | 17.8 | 20.5 | 600 |
| **hidden** — replay, console `visibility: hidden` | 3, 4, 4 | **4** | 18.2 | 66.4 | 554 |
| **painted** — identical replay, everything drawn | 4, 4, 3 | **4** | 18.3 | 65.2 | 553 |

**`addedDrops = 0`, `p95Delta = 0.1 ms` against 4 ms of headroom,
`passes: true`.** Live arm, recorded and not graded: 152 frames, p50 16.6,
p95 18.1, max 69.0, 3 over 34 ms.

The painted arm's absolute p95 of 18.3 ms also clears the **retired** bar of
≤ 20 ms; only its 4 drops keep `meetsLegacyBar` false, and the hidden control
drops the same 4 with nothing of ours painted, which is the whole reason the
criterion was amended.

**Across five measurements of this comparison on three commits:**

| commit | context | hidden median | painted median | addedDrops | verdict |
| --- | --- | ---: | ---: | ---: | :---: |
| `601baef` | alone | 4 | 5 | 1 | FAIL |
| `8ae40ec` | alone (1st) | 3 | 3 | **0** | PASS |
| `8ae40ec` | full suite | 3 | 4 | 1 | FAIL |
| `8ae40ec` | alone (2nd) | 6 | 7 | 1 | FAIL |
| **`c2966e7`** | **alone** | **4** | **4** | **0** | **PASS** |

RV3 grades T2.8 **PASS** on this pass's measurement, and says plainly what that
is worth: the effect being measured is 0–1 dropped frames out of ~550 intervals,
and the control's own median has ranged 3 to 6 across five runs on one machine.
The honest summary is that **the console's own cost is at or below the noise
floor of the instrument**, which is what the amended criterion asks and is a
weaker claim than "zero".

## 3. The two captures the round was about

**`T3/after-1180.png` — fixed.** The sheet now ends clear of the control rail
instead of running under it. Its **`Copy Markdown` and `✕` row is visible**, all
six score bars are complete with their `3/5` readouts inside the sheet, and
nothing is cut mid-word at the right edge. At `8ae40ec` this same capture had the
bars running under the rail, the header row gone entirely, and the body cut at
"…was called and r". The `--rail-cover-*` inset does what it says.

*(One thing unchanged and not a regression: the sticky `2 CITED SOURCES` footer
sits over the scrolling body, so the paragraph continues underneath it. That is
the same at 1440 and in every earlier pass.)*

**`S/failure.png` — the raw code is gone.** The failing node card's error now
reads `SyntheticRefusal: Synthetic failure: fm_cast_refusal attempt 1
(SyntheticRefusal)`. At `8ae40ec` it read `SYNTHETIC_FAILURE:` in that position —
the observation RV3 filed as fourth-pass note 2, **now closed**. The text wraps
at word boundaries onto three lines with no mid-word cut, and the trace rail's
matching row clips with an ellipsis at a word boundary
(`…: fm_cast_refusal…`). One `Run failed` banner, not stacked; the phase lane
names the failing step; the status rail says `Failed`.

Two things still visible and still not defects: the lane label renders the
node id upcased as `FM_CAST_REFUSAL`, which is the **author's own** id from the
spec's graph rather than an internal code; and the four nodes are drawn on top
of one another because that spec gives every node `position: {x: 0, y: 0}`.

## 4. The table

Rows this pass re-measured are marked *(re-run)*. Every other row **carries its
fourth-pass verdict unchanged**, and says so — round six touched five frontend
files and no test, fixture or Python, so a row it cannot reach is not re-argued.

| Id | Verdict | Evidence | What RV3 saw at `c2966e7` |
| --- | :---: | --- | --- |
| **G1** | NOT VERIFIED BY ME | `evidence/G1/` | RV2's. Untouched in all five passes. |
| **G2** | **PASS** *(re-run)* | `G2/grep.txt` | **1 hit, 0 product hits** — the `readsAsRole()` JSDoc example, now at `:138`. Re-run because round six touched **two** of the four files it covers. Worth naming: the new error humaniser turns `SYNTHETIC_FAILURE` into `Synthetic failure` by **reshaping whatever matches `/\b[A-Z][A-Z0-9_]{3,}\b/`** (`interpret.ts:192`), not by looking a token up — a lookup table of known codes would have shown here as a hit, and there is none. |
| **G3** | **PASS** *(re-run)* | `G3/vitest.txt`, `R/playwright.txt` | `cast.spec.ts:998`'s reload check green (15.3 s); the 20-role cross-process snapshot green inside 1987/1987. |
| **G4** | NOT VERIFIED BY ME | `G4/roles-sheet.png` | RC's Q4. |
| **T1.1** | NOT VERIFIED BY ME | both report headers, `T1/cold-read.md`, `RC/answers.md` | `cast.spec.ts:1682` green; both headers rewritten this pass. The verdict is the orchestrator's grading of RC's answers. |
| **T1.2** | **PASS** *(re-run)* | `T1/vitest.txt`, `T3/after-1180.png` | Unit green, and now legible at 1180 as well as 1440: `NEEDS WORK 6.0/10`, `Moderate confidence · 62%`, `Provisional · not a final answer`, `Thin evidence · Demand and Headroom over free`, every dimension in words with a `thin` chip where the evidence is thin. |
| **T1.3** | **PASS** *(re-run)* | `R/playwright.txt`, `S/failure.png`, `T1/enum-audit.md` | `cast.spec.ts:2095` green, and the fourth pass's one observation is closed: the raw `SYNTHETIC_FAILURE` is off the node card too, not just out of the trace line. |
| **T1.4** | **PASS** *(carried, pass 4)* | `T1/vitest.txt` | Unknown floor code / dimension key / band render as words; green inside this pass's 1987/1987. |
| **T1.5** | **PASS** *(re-run)* | `T1/data-layer-diff.txt` | All three diffs **empty**, `config.py` untouched. Five passes, five empty answers. |
| **T2.1** | **PASS** *(re-run)* | `T2/interpretation-vitest.txt`, `T2/trace-completed.png` | `cast.spec.ts:1183` green in a browser; the unit half green inside 1987/1987. |
| **T2.2** | **PASS** *(re-run)* | `T2/vocabulary.md` | The serializer's ladder has never changed on this branch. `interpret.ts` gained 27 lines — an error humaniser, not a new row — and all sixteen `FrameKind` values still have a row. |
| **T2.3** | NOT VERIFIED BY ME | `T2/characters-32px.png`, `T2/states-32px.png` | RC's Q4; the sheets predate the bun crest (note 3). |
| **T2.4** | **PASS** *(carried, pass 4)* | `CHARACTERS.md`, `G3/vitest.txt` | Round six did not touch `pip.ts` or the identity ladder. |
| **T2.5** | **PASS** *(re-run)* | `T2/no-timers.txt` | Re-run because round six added 24 lines to the one file the hits live in. Still **exactly three**, now at `:254`, `:285`, `:821`; `frontend/src/characters/` and `AgentCharacter.vue` return **zero** for all five clock routes. |
| **T2.6** | **PASS** *(re-run)* | `T2/tie-in.png` | `cast.spec.ts:907` green (2.9 s). |
| **T2.7** | **PASS** *(re-run)* | `T2/reduced-motion.png` | `:1062` and `:1101` green. |
| **T2.8** | **PASS** *(re-run)* | `T2/perf.json` | Section 2. `addedDrops = 0`, `p95Delta = 0.1`, `passes: true`. |
| **T2.9** | **PASS** *(carried, pass 4)* | `T2/rowers-grep.txt`, `T2/node-running.png` | The three real class names return **zero** across `frontend/src`; round six did not reintroduce them (`WorkflowNode.vue` +17 lines, all error text). |
| **T3.1** | **PASS** *(carried, pass 4)* | `T3/scope-order.txt` | A fact about the branch's first two commits; six rounds of `studio.css` edits cannot alter it. |
| **T3.2** | **PASS** *(re-run)* | `T3/literals.txt` | `designTokens.spec.ts` green inside this pass's 1987/1987, after a round that added 46 lines of `studio.css` and new `--rail-cover-*` variables. |
| **T3.3** | **PASS** *(re-run)* | `T3/contrast.md`, `T3/contrast-rv3-rerun.txt` | **exit 0**, 236 pairings, 234 in scope, **0 failing**, byte-identical to the committed file. The `--rail-cover-*` work is geometry, not colour, and the sheet measures exactly as it did. |
| **T3.4** | **PASS** *(re-run)* | all `before-*` and `after-*` | All four "after" captures rewritten and looked at; 1180 is the one that changed and it changed for the better (section 3). |
| **T3.5** | **PASS** *(re-run)* | `T3/builder-visual.txt` | **16/16 green, no regeneration**, md5s identical. Five passes, five greens, no regeneration in any. |
| **S1–S6** | **PASS** *(re-run)* | `S/*.png`, `S/long-run.md` | All ten `cast.spec.ts` tests green. `S/failure.png` is section 3. |
| **R1** | **FAIL** | `R/*` | **This pass is targeted, and R1 is the one row that needs the full suite.** Cited from `8ae40ec`: **163 tests, 160 passed, 3 failed, 0 skipped, 12.8 m** — `builder.spec.ts:1227` (proved pre-existing on `main`, `R/builder-1227.md`), `builder.spec.ts:1552` (item-44, passes alone) and `cast-perf.spec.ts:550` (which passes alone, and passes again here). Everything targeted at `c2966e7` is green: **38 Playwright tests across four specs, 1987 Vitest, `vue-tsc` 0, `npm run build` 0, contrast 0.** On this evidence the only red a full suite would still show is the builder drag pair, one of which is not this branch's. |
| **R2** | **PASS** *(re-run)* | `R/diff-stat.txt` | Four forbidden surfaces each **NO DIFF**; `git diff 16f3be5..HEAD -- src/` **empty** — no `src/brief_crew` file has changed since the first pass, six rounds ago. |

## 5. Things a reader should know that no criterion asks for

1. **The Python suite was not re-run this pass**, and does not need to be: no
   Python changed, which `R/diff-stat.txt` proves with an empty
   `git diff 16f3be5..HEAD -- src/`. `R/python.txt` therefore carries the fourth
   pass's **2544 / OK / 6 skipped** and says so at the top.
2. **`builder.spec.ts:1227` is pre-existing, and measured.**
   `evidence/R/builder-1227.md`: five runs at HEAD and five on a worktree of
   `main`, one shared backend, byte-identical spec, and the `main` arm proved to
   be `main`. **HEAD 0/5 pass, `main` 1/5 pass**, identical call log — the
   problems dock's `problem-message` span intercepts pointer events over the
   attach port. It should be split out of remaining-work item 44, which records
   this class as flaky-but-passing-alone.
3. **Three artifacts still predate the character they show.** `RC/answers.md`
   and `T1/cold-read.md` are timestamped 16:33, and `G4/roles-sheet.png`,
   `T2/characters-32px.png` and `T2/states-32px.png` were last written before the
   bun crest replaced the halo. G4, T2.3 and T1.1 all turn on a reader looking at
   those; they should be regenerated and re-read before they are graded. None is
   RV3's.
4. **`benchmarks/perf/canvas.json` is modified in the working tree**, by
   `e2e/builder-perf.spec.ts` on the fourth pass's full run. A suite side-effect,
   left as written.
5. **Tally: 26 PASS, 1 FAIL, 4 NOT VERIFIED BY ME** over the 31 rows.
   Pass 4 was 25 / 2 / 4; pass 3 was 25 / 2 / 4; pass 2 was 22 / 5 / 4; pass 1
   was 19 / 8 / 4. **T2.8 has gone green**, and the single remaining FAIL is
   **R1** — which now rests on one test proved pre-existing on `main` and one
   that passes when run alone.

---
---

# FOURTH PASS — `8ae40ec`, 2026-09-05

## 0. No stale dev server existed, and that was checked before anything ran

`playwright.config.ts` sets `reuseExistingServer: true`, so a Vite left running
from an earlier session would serve an older bundle to every capture and nothing
would say so. That was the leading explanation for the third pass's see-through
`after-1440.png`. It is not the explanation, and here is the check:

```
netstat -ano | findstr :527          -> no LISTENER on 5273, 5274 or 5275
every node/serve/python/vite process -> none listening on any port at all
Stop-Process -Name serve -Force      -> ran; nothing left to stop
GET http://127.0.0.1:5273/ 5274 5275 -> no answer, all three
```

So Playwright started its own Vite from this tree. **The real explanation is the
commit history**: the sheet was still translucent at `601baef`, where that
capture was taken, and `fec004d` made it opaque. A run at `fec004d` confirmed
it — `run-canvas.spec.ts` was green there with no regeneration at all.

## 1. What was run, and against what

| | |
| --- | --- |
| Python | `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .` — **2544 tests, OK, 6 skipped, 173.4 s**, exit 0 |
| Vitest | `npx vitest run` from `frontend/` — **93 files, 1979 tests, 0 failed**, exit 0 |
| Types | `npx vue-tsc -b --force` — **exit 0**, no diagnostics |
| Build | `npm run build` — **exit 0**, built in 703 ms |
| E2E, full | `npx playwright test`, both projects — **163 tests: 160 passed, 3 failed, 0 skipped, 12.8 m**, exit 1 |
| Contrast | `node scripts/contrast-audit.mjs` — **exit 0**, 236 pairings, 234 in scope, **0 failing** |

Backend: `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099` with
`CREDENTIALS_MASTER_KEY`, `BUILDER_ALLOW_GATELESS_GRAPHS=1`,
`RUN_RATE_LIMIT_MAX_RUNS=100`, `MCP_ALLOW_INSECURE_LOCAL=1`, `SKILLS_ROOT`, and
the six-mode `SYNTHETIC_FAILURE`. MCP fixture on :8791 with `E2E_MCP_URL`
exported, hence **0 skipped**. Money spent: **zero**.

> **One incident, recorded because it could have been mistaken for a defect.**
> The backend was killed by something outside this session partway through the
> pass — no traceback in its log, wrapper exit 127, `/healthz` at 000 while
> `cast.spec.ts` was starting. That run was **abandoned rather than reported**:
> stopped, backend restarted (pid recorded), and `cast + studio` re-run from
> scratch against the live one. `MISSION.md` warns that
> `Stop-Process -Name serve` kills every backend on the machine; this has the
> shape of exactly that, from another shell.

## 2. T2.8 against the amended row — every arm, every sample, three runs

The criterion: three arms in one run, graded on the **median** of each arm —
`over34ms(painted) ≤ over34ms(hidden)` and `p95(painted) ≤ p95(hidden) + 4 ms`,
with all absolutes printed. The spec now takes **six alternating arms**
(H/P/H/P/H/P) precisely because the hidden control moved between runs.

**The comparison was run three times on this one commit.** All three are below;
`perf.json` holds the third.

| run | context | idle | hidden samples → median | painted samples → median | addedDrops | p95Δ | verdict |
| --- | --- | --- | --- | --- | ---: | ---: | :---: |
| 1 | `cast-perf` alone (step 5) | 0 over 34 ms, p95 17.7 | 2, 3, 3 → **3** (p95 18.1) | 3, 3, 2 → **3** (p95 18.1) | **0** | 0.0 | **PASS** |
| 2 | inside the full suite | 0 over 34 ms, p95 17.9 | 3, 4, 3 → **3** (p95 18.1) | 3, 4, 4 → **4** (p95 18.1) | **1** | 0.0 | FAIL |
| 3 | `cast-perf` alone again | 0 over 34 ms, p95 18.1 | 6, 8, 6 → **6** (p95 18.2) | 3, 9, 7 → **7** (p95 18.3) | **1** | 0.1 | FAIL |

Live run, recorded and not graded: 151–152 frames, p95 17.9–18.3, max 67.7–82.0,
**3 over 34 ms** every time.

**Verdict: FAIL, by one dropped frame, in two runs of three.** RV3 will not
round that to a pass, and will not pretend it is a large finding either:

* The **p95 arm passes outright in all three runs** — the console costs 0.0 to
  0.1 ms of p95 against 4 ms of allowance — and the painted arm's absolute p95
  (18.1–18.3 ms) also clears the *retired* bar of ≤ 20 ms, which no earlier pass
  managed (32.3, then 26.8).
* The **idle floor is 0 in all three runs**, so the machine is not the problem.
* The effect is **one frame in ~550 intervals**, and the control itself moved
  from a median of 3 to a median of 6 between two runs twenty minutes apart. The
  measurement's own noise is the same size as the thing it is measuring. Run 3's
  painted samples were 3, 9 and 7 — a threefold spread within one arm.
* So: the console's own cost is at most one dropped frame, it is not reliably
  distinguishable from zero, and the criterion as written says that is a fail.

## 3. The table

Rows this pass re-measured are marked; every other row carries its third-pass
verdict, and where it does, the row says so.

| Id | Verdict | Evidence | What RV3 saw at `8ae40ec` |
| --- | :---: | --- | --- |
| **G1** | NOT VERIFIED BY ME | `evidence/G1/` | RV2's. Untouched in all four passes. |
| **G2** | **PASS** *(re-run)* | `G2/grep.txt` | **1 hit, 0 product hits** — the `readsAsRole()` JSDoc example, judged again rather than carried. Round five rewrote 61 lines of `pip.ts` (612 lines now, from 526 at the first pass), which is exactly the edit that types a role name into a shape table by accident. It did not. |
| **G3** | **PASS** *(re-run)* | `G3/vitest.txt`, `R/playwright.txt` | The 20-role snapshot fixture still asserts across processes; `cast.spec.ts:998`'s reload check green (15.6 s). |
| **G4** | NOT VERIFIED BY ME | `G4/roles-sheet.png` | RC's Q4. The sheet predates the bun crest; see note 4. |
| **T1.1** | NOT VERIFIED BY ME | both report headers, `T1/cold-read.md`, `RC/answers.md` | `cast.spec.ts:1682` green — both headers rewritten this pass, including the `INSUFFICIENT_EVIDENCE`-with-a-listed-floor case. The cold read on disk still predates them; see note 4. |
| **T1.2** | **PASS** *(re-run)* | `T1/vitest.txt`, `T3/after-1440.png` | Unit green. And visible in the capture: `NEEDS WORK 6.0/10`, `Moderate confidence · 62%`, `Provisional · not a final answer`, `Thin evidence · Demand and Headroom over free`, every dimension named in words with a `thin` chip where the evidence is thin. No codes. |
| **T1.3** | **PASS** *(re-run)* | `R/playwright.txt`, `T1/enum-audit.md` | `cast.spec.ts:2095` green: no raw code in the trace's error line. One honest observation in note 2 about the failing *node card*, which is outside this criterion's three named surfaces. |
| **T1.4** | **PASS** | `T1/vitest.txt` | Unknown floor code / dimension key / band still render as words. |
| **T1.5** | **PASS** *(re-run)* | `T1/data-layer-diff.txt` | All three diffs **empty**, `config.py` untouched. Four passes, four empty answers. |
| **T2.1** | **PASS** *(re-run)* | `T2/interpretation-vitest.txt`, `T2/trace-completed.png` | Unit green; `cast.spec.ts:1183` green in a browser. Both halves. |
| **T2.2** | **PASS** *(re-run)* | `T2/vocabulary.md` | `interpret.ts` is byte-identical to the third pass and the serializer's ladder has never changed on this branch; all sixteen `FrameKind`s still rowed. |
| **T2.3** | NOT VERIFIED BY ME | `T2/characters-32px.png`, `T2/states-32px.png`, `T2/originality.md` | RC's Q4. The sheets predate the bun crest; note 4. |
| **T2.4** | **PASS** | `CHARACTERS.md`, `G3/vitest.txt` | Green, including the empty-role fallback. |
| **T2.5** | **PASS** *(re-run)* | `T2/no-timers.txt` | Regenerated. Still **exactly three hits, all in `useRunChoreography.ts`** (`:253` injectable `now`, `:284`/`:799` the 200 ms arrival receipt), and `frontend/src/characters/` + `AgentCharacter.vue` return **zero** for all five clock routes — after a round that rewrote the crest. |
| **T2.6** | **PASS** *(re-run)* | `T2/tie-in.png` | `cast.spec.ts:907` green (2.8 s). |
| **T2.7** | **PASS** *(re-run)* | `T2/reduced-motion.png` | `:1062` and `:1101` green. |
| **T2.8** | **FAIL** *(re-run)* | `T2/perf.json`, `T2/perf-notes.md` | Section 2. One dropped frame at the median, in two runs of three; p95 arm passes in all three. |
| **T2.9** | **PASS** *(re-run)* | `T2/rowers-grep.txt`, `T2/node-running.png` | Regenerated and re-captured at `8ae40ec`. The grep file now carries the two greps that actually answer the criterion, not only the one it names: `node-crew-rower\|node-crew-oar\|node-crew-hull` returns **zero** across all of `frontend/src`, and the only `node-rower\|node-oar` hit is a retirement comment. The throwaway capture asserted 0/0/0 rowers and exactly 1 character on the running card. |
| **T3.1** | **PASS** *(re-run)* | `T3/scope-order.txt` | `fcdbadf` 14:09:00 precedes `fd84f57` 14:25:50 by 16 m 50 s — a fact about the first two commits that four rounds of `studio.css` edits cannot alter. |
| **T3.2** | **PASS** | `T3/literals.txt` | 13 files, 0 colour literals, 9/9 green at the third pass; rounds four and five touched `tokens.css`, `studio.css` and `ReportPanel.vue`, and the spec runs inside the green `npx vitest run` above (1979/1979). |
| **T3.3** | **PASS** *(re-run)* | `T3/contrast.md`, `T3/contrast-rv3-rerun.txt` | **exit 0**, 236 pairings, 234 in scope, **0 failing**, byte-identical to the committed file. Four rows more than the third pass, because the script now models each ground rather than one shared stack — a stricter model, since an opaque surface's ratio does not vary with what is under it. |
| **T3.4** | **PASS** *(re-run)* | `before-*.png`, `after-1440/1180/390/1440-light.png` | All four "after" captures rewritten this pass and **looked at** — section 4. The comparison itself is RC's Q6. |
| **T3.5** | **PASS** *(re-run)* | `T3/builder-visual.txt` | **16/16 green, no regeneration**, md5s identical before and after. Four passes, four greens, no regeneration in any. |
| **S1** | **PASS** *(re-run)* | `S/empty.png` | `cast.spec.ts:727` green. |
| **S2** | **PASS** *(re-run)* | `S/first-run.png` | `:764` green (18.2 s). |
| **S3** | **PASS** *(re-run)* | `S/long-run.png`, `S/long-run.md` | `:1183` green; the capture is section 4. |
| **S4** | **PASS** *(re-run)* | `S/failure.png` | `:2095` green; the capture is section 4. |
| **S5** | **PASS** *(re-run)* | `T2/reduced-motion.png` | Written by the passing `:1101`. |
| **S6** | **PASS** *(re-run)* | `S/narrow.png`, `S/narrow-rail-open.png` | `:1867` green. The rail-open capture was **re-taken at this head** by a throwaway spec: one `.rail-scrim`, `rgba(10, 10, 10, 0.58)`, `backdrop-filter: none`, `scrollWidth = 390` with the rail open. |
| **R1** | **FAIL** *(re-run)* | `R/*` | Four suites green (2544 / 1979 / exit 0 / exit 0); Playwright **160 passed, 3 failed, 0 skipped**. All three baselines regenerated and named. Of the three reds, one is T2.8 and two are the builder drag pair — one of which is proved pre-existing on `main`. |
| **R2** | **PASS** *(re-run)* | `R/diff-stat.txt` | Three Python source files and five test modules. The four forbidden surfaces each print **NO DIFF**, and `git diff 16f3be5..HEAD -- src/` is **empty** — no `src/brief_crew` file has changed since the first pass. |

## 4. The captures, looked at

The orchestrator asked what is actually visible. All six were opened.

**`T3/after-1440.png` (dark) — no show-through.** The report sheet is fully
opaque; the canvas behind it is completely hidden, and so is the graph. Both
rails are opaque. The sheet carries its own header (`Copy Markdown`, `✕`), the
scores block, and the report body. **Nothing bleeds through anything.**

**`T3/after-1440-light.png` — no show-through, but three dark islands.** The
sheet is opaque in light too. What stands out instead is that the **app header,
the dialogue drawer at the top of the left rail, and the STATUS metrics block in
the right rail all stay dark** while the rest of the shell is ivory. The
contrast sheet passes on every one of them, so this is legibility-safe and it
may well be deliberate (dark chrome, a dark "well" for metrics, a dark drawer).
RV3 flags it because a light-theme screenshot with three dark islands reads as
half-converted to someone who has not been told, and no earlier pass recorded it.

**`T3/after-1180.png` (dark) — no show-through, but the sheet is clipped.** At
1180 the sheet's content is **cut off on the right** rather than reflowed: the
score bars run under the sheet's right edge, the body text is cut mid-word
("…was called and r"), and the sheet's own `Copy Markdown` / `✕` header row is
gone entirely. Nothing shows through — the content is simply lost at that width.
This is the one thing in the six captures RV3 would put in front of a designer.

**`S/long-run.png` — the newest line is visible, the drawer bottom clips a row.**
The trace is scrolled to the bottom and the last two rows are
`Validation report writer finished Reporting` and `Run / Run finished`, so S3's
"the newest line is visible" holds. The dialogue drawer occupies the upper half
and is separated from the trace list by a **drawn seam**, which is round five's
change and reads as intentional. The drawer's bottom edge clips the last
entry's `› Details` row mid-height — a partially visible row rather than a clean
cut. Minor, and it is what a scrolling drawer looks like mid-scroll.

**`S/narrow-rail-open.png` (390×844) — the scrim works.** The control rail is a
full-height overlay carrying the gate card (five fields, Approve/Revise,
`29:59 remaining`), and about 48 px of the shell behind it is left visible and
**dimmed**, not blurred — `rgba(10, 10, 10, 0.58)`, `backdrop-filter: none`,
which is exactly what `studio.css:1054`'s comment says it chose and why. The
header stays above the scrim and undimmed, also as the comment states. A `>`
chevron at bottom-left is the way back. `scrollWidth` is 390 with the rail open.

**`S/failure.png` — one banner, not stacked.** A single `Run failed` strip with
a `✕` at the top of the control rail. The phase lane reads `IDEA ✓ → SAFE ✓ →
FM_CAST_REFUSAL (3, red) → REPORT (4)`, so the failing step is named. The trace
carries plain-language error rows and the status rail says `Failed`. Two things
seen and reported rather than smoothed: the failing **node card** still shows the
raw `SYNTHETIC_FAILURE:` string in its error message (note 2), and the graph's
four nodes are drawn on top of one another because the spec's own document gives
every node `position: {x: 0, y: 0}` — that is the test's graph, not a product
defect.

## 5. Things a reader should know that no criterion asks for

1. **`builder.spec.ts:1227` is pre-existing and is not a flake.** Measured in a
   separate study, `evidence/R/builder-1227.md`: five runs at HEAD and five on a
   worktree of `main`, one shared backend, byte-identical spec file (md5
   `20243150…` both trees), and the `main` arm proved to be `main` by serving
   `WorkflowNode.vue` from its own Vite on :5275 and counting zero
   `AgentCharacter` in it. **HEAD 0/5 pass, `main` 1/5 pass**, with the same call
   log in every failing run: the problems dock's `problem-message` span
   *intercepts pointer events* over the attach port, and Playwright retries for
   the full 15 s against an occlusion that never lifts. Item 44 records this test
   as flaky-but-passing-alone; it fails alone, on both branches. It should be
   split out of item 44 and handed to whoever owns the dock.
2. **The raw `SYNTHETIC_FAILURE` string survives on the failing node card.** T1.3
   names three surfaces — a rendered report, a gate card and the status rail —
   and the node card is none of them, so this is not a T1.3 failure and the
   criterion's own browser assertion passes. But the token is on screen in
   `S/failure.png`, and a reader grading "no raw internal code reaches the run
   shell" from the picture would see it. Worth a decision, not a red.
3. **`perf.json` holds run 3 of three.** The graded standalone run (run 1,
   which passed) was overwritten when the full suite re-ran the same spec, and
   the standalone re-run afterwards produced run 3. All three are tabulated in
   section 2 so nothing rests on which one happens to be on disk.
4. **Three artifacts on disk predate the character they show.** `RC/answers.md`
   and `T1/cold-read.md` are timestamped 16:33, and `G4/roles-sheet.png`,
   `T2/characters-32px.png` and `T2/states-32px.png` were last written before
   round five replaced the halo with a bun crest. G4, T2.3 and T1.1 all turn on
   a reader looking at those, so they should be regenerated and re-read before
   they are graded. RV3 does not own any of them.
5. **`benchmarks/perf/canvas.json` is modified in the working tree**, by
   `e2e/builder-perf.spec.ts`, which rewrites it on every full run. A suite
   side-effect, left as the suite wrote it.
6. **Tally: 25 PASS, 2 FAIL, 4 NOT VERIFIED BY ME** over the 31 rows.
   Pass 3 was 25 / 2 / 4; pass 2 was 22 / 5 / 4; pass 1 was 19 / 8 / 4. The
   headline count has not moved since the third pass, and that understates the
   round: T2.8 went from failing by 1-and-5 added drops to failing by 1 in two
   runs of three while passing in the other, and every capture the S and T3 rows
   rest on was re-taken against an opaque sheet.
   The two FAILs are **T2.8**, by one dropped frame at the median in two runs of
   three, and **R1**, which is the roll-up: T2.8 plus the two builder drag tests,
   one of which is proved pre-existing on `main` and the other of which passes
   when run alone.

---
---

# THIRD PASS — `601baef`, 2026-09-05

## 1. What was run, and against what

| | |
| --- | --- |
| Python | `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .` — **2544 tests, OK, 6 skipped, 131.6 s**, exit 0 |
| Vitest | `npx vitest run` from `frontend/` — **93 files, 1963 tests, 0 failed**, exit 0 |
| Types | `npx vue-tsc -b --force` — **exit 0**, no diagnostics |
| Build | `npm run build` (`vue-tsc -b && vite build && tsc -p tsconfig.server.json`) — **exit 0**, built in 614 ms |
| E2E | `npx playwright test`, both projects — **163 tests: 159 passed, 4 failed, 0 skipped, 12.3 m**, exit 1 |
| Contrast | `node scripts/contrast-audit.mjs` — **exit 0**, 232 pairings, 230 in scope, **0 failing** |

Backend, restarted clean for this pass, its log read rather than `/healthz`
trusted:

```
SYNTHETIC=1  SYNTHETIC_BRANCH_DELAY_SECONDS=5  PORT=8099
CREDENTIALS_MASTER_KEY=Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE=
BUILDER_ALLOW_GATELESS_GRAPHS=1
RUN_RATE_LIMIT_MAX_RUNS=100            (.agent/MISSION.md section 8)
MCP_ALLOW_INSECURE_LOCAL=1             (.agent/MISSION.md section 8)
SKILLS_ROOT=D:/MultiAgentSystem/data/skills
SYNTHETIC_FAILURE="fm_bad_key:bad_key:1,fm_tool_timeout:tool_timeout:1,
                   fm_refusal:refusal:1,fm_malformed:malformed_output:1,
                   fm_rate_limit:rate_limit:1,fm_cast_refusal:refusal:1"
./.venv/Scripts/serve.exe
```

MCP fixture on :8791 with `E2E_MCP_URL` exported, so `builder-mcp.spec.ts` ran
rather than skipping — hence **0 skipped**. RV3 owned :8098, :8099, :8791 and
:5273 and nobody else was on the machine. Money spent: **zero**.

## 2. T2.8, graded against the amended row

The criterion was amended on 2026-09-05 after W4's profile: three arms in one
run, a **relative** budget, absolutes still printed. The console passes when
`over34ms(painted) ≤ over34ms(hidden)` and `p95(painted) ≤ p95(hidden) + 4 ms`.

**All three arms' absolute figures, from `evidence/T2/perf.json`** (the
full-suite sample the file holds):

| arm | intervals | p50 | p95 | max | over 34 ms | over 50 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **idle** — the page at rest | 600 | 16.6 | 18.0 | 23.1 | **0** | 0 |
| **hidden** — the same replay, console `visibility: hidden` | 555 | 16.6 | 18.3 | 74.4 | **4** | 2 |
| **painted** — the identical replay, everything drawn | 551 | 16.7 | 18.5 | 66.3 | **5** | 2 |

**Verdict: FAIL on the drop arm, PASS on the p95 arm.** `addedDrops = 1`
(5 painted against 4 hidden, and the rule is `≤`); `p95Delta = 0.2 ms` against
4 ms of headroom. `perf.json` records `passes: false`.

A second three-arm sample, taken twenty minutes earlier in the cast-only run on
the same machine and commit, read **idle 0 / hidden 5 / painted 10** —
`addedDrops = 5`, `p95Delta = 0.5`. So the painted arm added between one and
five drops over the hidden control across two samples, and never zero.

Two things the amendment is right about, and RV3 says so having argued the
other way in the first two passes: the **idle floor is 0** here, so this
machine is not the problem — but the **hidden control drops 4–5 frames with
nothing of ours painted**, which is exactly the harness cost the old absolute
bar was charging to the product. And the retired bar's p95 half is now met
outright: the painted arm reads **18.5 ms against the old ≤ 20 ms**, where the
first pass read 32.3 and the second 26.8. The live run — recorded, not graded —
reads 152 frames, p95 18.2, max 84.2, 3 over 34 ms.

## 3. The table

| Id | Verdict | Evidence | What RV3 saw at `601baef` |
| --- | :---: | --- | --- |
| **G1** | NOT VERIFIED BY ME | `evidence/G1/` | RV2's, complete on disk. RV3 did not touch G1 or G4. |
| **G2** | **PASS** | `G2/grep.txt` | Re-run and re-judged: **1 hit, 0 product hits**, the same JSDoc example in `readsAsRole()`. Worth re-running: round three rewrote 91 lines of `interpret.ts` and 51 of `pip.ts`, which is exactly when a role name gets typed into a table by accident. |
| **G3** | **PASS** | `G3/vitest.txt`, `G3/playwright.txt`, `reload-map.json` | **2 files, 74 tests green** (69 last pass) over the committed 20-role snapshot generated in one process and asserted in another; the browser reload check green again (`cast.spec.ts:842`, 15.2 s). |
| **G4** | NOT VERIFIED BY ME | `G4/roles-sheet.png` | RC's Q4. |
| **T1.1** | NOT VERIFIED BY ME — **and its cold read is now against a superseded picture** | `T1/report-header.png`, `T1/report-header-insufficient.png`, `T1/cold-read.md`, `RC/answers.md` | Round three added a capture test that replays a **real serializer verdict frame** (`cast.spec.ts:1453`, green first time) and it writes **both** headers — the override case and the new `INSUFFICIENT_EVIDENCE`-with-a-listed-floor case. RC has two pictures to read instead of none. **But the timestamps do not line up**: `RC/answers.md` and `T1/cold-read.md` were written at **16:33**, against the second pass's capture; this pass rewrote `report-header.png` at **17:30**, after round three changed the report panel (readable score bars, generic gate copy) and added the second header RC has never seen. Grading T1.1 on those answers would be grading a picture that no longer exists. The verdict is the orchestrator's; the staleness is RV3's to report. |
| **T1.2** | **PASS** | `T1/vitest.txt` | 2 files / **27 tests green**. |
| **T1.3** | **PASS** | `T1/vitest.txt`, `T1/enum-audit.md`, `R/playwright.txt` | **Fixed.** The second pass's browser red — `Run failed: SYNTHETIC_FAILURE: fm_cast_refusal attempt 1…` reaching the trace — is gone: `cast.spec.ts:1819` now passes, `rawCodesIn()` returns nothing on the error line, and the unit half stays green. |
| **T1.4** | **PASS** | `T1/vitest.txt` | Unknown floor code / dimension key / band still render as words. |
| **T1.5** | **PASS** | `T1/data-layer-diff.txt`, `R/python.txt` | All three diffs **empty**, `config.py` untouched. Round three's third verdict frame is a *fixture* and a *test* (`tests/events/test_verdict_frame.py`, `backendVerdictFrames.json`) — nothing that computes a verdict moved. Python **2544 OK**, the two new tests being that fixture's. |
| **T2.1** | **PASS** | `T2/interpretation-vitest.txt`, `T2/trace-completed.png`, `R/playwright.txt` | **Fixed, and both halves now hold.** Unit: 2 files / **76 tests green** (66 last pass) over both real frame logs. Browser: the 24-empty-rows red is gone — `cast.spec.ts:1027` passes and writes `trace-completed.png`. |
| **T2.2** | **PASS** | `T2/vocabulary.md` (RV3 section appended each pass) | Re-walked, because this time the subject moved: `interpret.ts` +91 lines. The **serializer ladder did not change** (`git diff 16f3be5..HEAD -- events/serializer.py` is empty), all sixteen `FrameKind`s still have a row, and the three rows whose wording changed are described by shape rather than exact string. |
| **T2.3** | NOT VERIFIED BY ME | `T2/characters-32px.png`, `T2/originality.md`, `T2/states-32px.png` | All refreshed in round three (`blocked-error` wears x_x eyes, the small crests grew). The verdict is RC's Q4 and the shape cue on the error state is exactly what Q4 should now be asked about. |
| **T2.4** | **PASS** | `CHARACTERS.md`, `G3/vitest.txt` | Green, including the empty-role fallback to the node id. |
| **T2.5** | **PASS** | `T2/no-timers.txt`, `T2/states-32px.png` | Re-ran the grep: still **exactly three hits, all in `useRunChoreography.ts`** (`:253` injectable `now`, `:284`/`:799` the 200 ms arrival receipt). `frontend/src/characters/` and `AgentCharacter.vue` return **nothing**, even for `performance.now` and `requestAnimationFrame` — which a round that rewrote `pip.ts` and `character.css` could easily have broken. |
| **T2.6** | **PASS** | `T2/tie-in.png`, `R/playwright.txt` | `cast.spec.ts:751` green (3.0 s) in both runs. |
| **T2.7** | **PASS** | `T2/reduced-motion.png`, `R/playwright.txt` | `:906` (offscreen, ≤ 12 live animations) and `:945` (reduced motion keeps every `data-state`) both green. |
| **T2.8** | **FAIL** (drop arm) / PASS (p95 arm) | `T2/perf.json`, `T2/perf-notes.md`, `R/playwright.txt` | Section 2 above. Painted adds 1 drop over hidden in the recorded sample and 5 in the other; p95 adds 0.2 ms against 4 ms of headroom. Idle floor 0. |
| **T2.9** | **PASS** | `T2/rowers-grep.txt`, `T2/node-running.png` | Re-captured at `601baef` by a throwaway spec (created, run, deleted) that asserted at the shutter: **0** `.node-crew-oar`, **0** `.node-crew-rower`, **0** `.node-crew-hull`, exactly **1** `[data-testid="node-agent-character"]`; the card read `data-character="market evidence analyst"`, `data-state="working"`. The only `node-rower|node-oar` in `frontend/src` is the retirement comment at `node-card.css:210`. |
| **T3.1** | **PASS** | `T3/scope-order.txt` | `SHELL-SCOPE.md` `fcdbadf` 14:09:00 precedes `studio.css` `fd84f57` 14:25:50 by 16 m 50 s. |
| **T3.2** | **PASS** | `T3/literals.txt` | **13 files, 0 colour literals**, 9/9 green. Round three rewrote `character.css`, `motion.css` and 86 lines of `studio.css` and added tokens; the inventory is still all zeros. |
| **T3.3** | **PASS** | `T3/contrast.md`, `T3/contrast-rv3-rerun.txt` | **The script exits 0**: 232 pairings, 230 in scope, **0 failing**, and the exit code has counted every in-scope row since round two. Byte-identical to the committed file (md5 `2f6f1c9f…` was pass 2; this pass's md5 matches the committed one exactly). The catalogue shrank 330 → 232 and RV3 did not wave that past — see section 5, note 1. |
| **T3.4** | **PASS** (artifacts) | all `before-*` and `after-1440/1180/390/1440-light.png` | Every capture present and rewritten this pass. The comparison is RC's Q6. |
| **T3.5** | **PASS** | `T3/builder-visual.txt` | **16/16 green, 43.0 s, no baseline regenerated** — md5s identical before and after, all sixteen listed. Third pass, third green, no regeneration in any of them. |
| **S1** | **PASS** (artifact) | `S/empty.png` | `cast.spec.ts:571` green. |
| **S2** | **PASS** | `S/first-run.png` | `cast.spec.ts:608` green (18.5 s). |
| **S3** | **PASS** | `S/long-run.png`, `S/long-run.md` | The 119-event test is green outright this pass, so these are the artifacts of a passing run rather than of a run that died after taking them. |
| **S4** | **PASS** | `S/failure.png` | `cast.spec.ts:1819` green: the failing node wears the blocked-error character (now with x_x eyes) and the trace says why in one sentence with no raw code in it. |
| **S5** | **PASS** (artifact) | `T2/reduced-motion.png` | Written by the passing `:945`. |
| **S6** | **PASS** | `S/narrow.png`, `S/narrow-rail-open.png`, `R/playwright.txt` | `cast.spec.ts:1626` green (18.5 s). Plus the extra capture asked for: a throwaway spec launched a run at 390×844, waited for the scope gate, opened the activity rail (`aria-label="Expand activity rail"`), found **exactly one** `.rail-scrim` element painted, and measured `document.scrollingElement.scrollWidth = 390` with the rail open. `studio.css:1054` carries the scrim only inside the 390 block, deliberately with **no** `backdrop-filter` — the comment says why, and it is the same reasoning as round three's four blur removals. |
| **R1** | **FAIL** | `R/python.txt`, `vitest.txt`, `typecheck.txt`, `build.txt`, `playwright.txt`, `baselines.md` | Four suites green (2544 / 1963 / exit 0 / exit 0); Playwright **159 passed, 4 failed, 0 skipped**. All three baselines regenerated and named. Breakdown in section 4. |
| **R2** | **PASS** | `R/diff-stat.txt` | Three Python source files and no more, plus five test modules. The four forbidden surfaces each print **NO DIFF**. And `git diff 16f3be5..HEAD -- src/` is **empty**: rounds two and three changed no Python source at all. |

## 4. The four Playwright failures

| test | what it is |
| --- | --- |
| `cast-perf.spec.ts:529` | **T2.8 itself.** Section 2. |
| `studio.spec.ts:360` | **A new red, and it is round two's mistake made again one round later.** Round three's generic gate copy renamed the derived heading and the assertion was not updated: `Expected substring: "Computed by the validator"` / `Received string: "Computed by the run"`. This test **passed in the second pass**. |
| `builder.spec.ts:1552` | The item-44 drag class. Re-run alone once and **passed** (2.4 s). Declared. |
| `builder.spec.ts:1227` | The item-44 drag class — **but this pass it FAILED ALONE TOO**, same `locator.hover` timeout on the `tool_1` attach handle, where in the first and second passes it passed alone in under three seconds. One re-run is what RV3 is allowed and it was spent; on this evidence the test cannot be called a flake this pass, and RV3 does not call it one. |

## 5. Things a reader should know that no criterion asks for

1. **T3.3's catalogue shrank 330 → 232 pairings, and RV3 checked what that
   bought.** 96 rows are the twelve character colours across four backgrounds,
   and round three re-classified them from "small text at 4.5" to "a figure at
   3.0" — WCAG 1.4.11 rather than 1.4.3, on the ground that the medallion holds
   a drawn character rather than two initials. That is a defensible reading and
   it is still a loosening, so:

   ```
   $ grep 'as a figure on' contrast-human.txt | wc -l                -> 96
   $ grep 'as a figure on' contrast-human.txt | awk '$1 < 4.5' | wc -l -> 0
   lowest figure ratio on the sheet: 4.64
   ```

   **Not one of the 96 rows depends on the relaxation** — every one clears the
   old 4.5 text bar as well. Three further rows left because the elements no
   longer exist (the M2 version mark, `ChatRail`'s `.text-button` and
   `.call-chip`), and one row was **added**: `the node state chip`, which exists
   because `run-canvas.spec.ts:243` caught the cascade inversion RV3's second
   pass reported. The sheet and the E2E now assert the same fact from opposite
   sides.
2. **`perf.json` now carries both arms of the criterion**, which it did not in
   either earlier pass — the live run is recorded (and explicitly *not graded*)
   alongside the three-arm comparison. That was RV3's note-2 from the second
   pass and it is closed.
3. **`benchmarks/perf/canvas.json` is modified in the working tree**, by
   `e2e/builder-perf.spec.ts`, which rewrites it on every full run. A suite
   side-effect, not an edit; left as the suite wrote it.
4. **The Python suite makes a live Pinecone `describe_index` call** with `.env`
   present. Read-only, free, pre-existing — but the suite is not network-free on
   this machine.
5. **Every cold-reader answer on disk predates the pictures it describes.**
   `RC/answers.md` and `T1/cold-read.md` are timestamped **16:33**; this pass
   rewrote every capture RC's questions name between **17:28 and 17:45**, and
   round three changed the report panel, the trace row, the dialogue header, the
   error line, the `blocked-error` eyes, the small crests and the 390 rail. Four
   of RC's seven questions (Q1–Q3 on the report header, Q4 on the roles sheet,
   Q5 on the trace, Q7 on the S states) are therefore answered about images that
   no longer exist. The four rows that turn on them — T1.1, G4, T2.3 and the
   reading half of the S rows — should be re-read before they are graded. RV3
   does not grade them and did not touch either file.
6. **Tally: 25 PASS, 2 FAIL, 4 NOT VERIFIED BY ME** over the 31 rows.
   Pass 2 was 22 / 5 / 4; pass 1 was 19 / 8 / 4. Only two rows still fail:
   **T2.8**, on its drop arm alone, and **R1**, which is the roll-up — failing
   on T2.8 plus one stale copy assertion (`studio.spec.ts:360`) and one drag
   test that no longer passes alone (`builder.spec.ts:1227`). The four
   NOT VERIFIED rows are all somebody else's to sign: G1 and G4 are RV2's and
   RC's, T1.1 and T2.3 wait on RC's answers — and T1.1's *inputs*, missing for
   two passes, are now on disk as two report headers.

---
---

# SECOND PASS — `16f3be5`, 2026-09-05

## 1. What was run, and against what

| | |
| --- | --- |
| Python | `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .` — **2542 tests, OK, 6 skipped, 132.9 s**, exit 0 |
| Vitest | `npx vitest run` from `frontend/` — **93 files, 1936 tests, 0 failed**, exit 0 |
| Types | `npx vue-tsc -b --force` — **exit 0**, no diagnostics |
| Build | `npm run build` (`vue-tsc -b && vite build && tsc -p tsconfig.server.json`) — **exit 0**, built in 672 ms |
| E2E | `npx playwright test`, both projects — **162 tests: 155 passed, 7 failed, 0 skipped, 12.2 m**, exit 1 |

Backend, started from the repo root in the background, its log read rather than
`/healthz` trusted, and restarted clean for this pass:

```
SYNTHETIC=1  SYNTHETIC_BRANCH_DELAY_SECONDS=5  PORT=8099
CREDENTIALS_MASTER_KEY=Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE=
BUILDER_ALLOW_GATELESS_GRAPHS=1
RUN_RATE_LIMIT_MAX_RUNS=100            (.agent/MISSION.md section 8)
MCP_ALLOW_INSECURE_LOCAL=1             (.agent/MISSION.md section 8)
SKILLS_ROOT=D:/MultiAgentSystem/data/skills
SYNTHETIC_FAILURE="fm_bad_key:bad_key:1,fm_tool_timeout:tool_timeout:1,
                   fm_refusal:refusal:1,fm_malformed:malformed_output:1,
                   fm_rate_limit:rate_limit:1,fm_cast_refusal:refusal:1"
./.venv/Scripts/serve.exe
```

The `SYNTHETIC_FAILURE` value is `failure-modes.spec.ts`'s five-mode string
combined with `cast.spec.ts`'s sixth, which the grammar allows —
`builder_runner.py::parse_synthetic_failures` splits on commas and each entry
carries its own node prefix. The MCP fixture ran on :8791 with `E2E_MCP_URL`
exported, which is why the suite reports **0 skipped**. RV2's ports (:8098,
:5274) were never touched. Money spent: **zero**.

## 2. The table

| Id | Verdict | Evidence | What RV3 saw at `16f3be5` |
| --- | :---: | --- | --- |
| **G1** | NOT VERIFIED BY ME | `evidence/G1/` | RV2's, and complete on disk. RV3 did not touch G1, G4 or port 8098. |
| **G2** | **PASS** | `evidence/G2/grep.txt` | Re-run, not carried forward: **one hit, zero product hits**, the same JSDoc line in `readsAsRole()` quoting `Scoper` as an example. Worth re-running because round two grew `AgentCharacter.vue` 92 → 197 lines and `useRunChoreography.ts` 958 → 1024, and the answer did not change. |
| **G3** | **PASS** | `G3/vitest.txt`, `G3/playwright.txt`, `G3/reload-map.json` | **2 files, 69 tests green** over the committed 20-role snapshot generated in one process and asserted in another; the reload check passed again (`cast.spec.ts:778`, 15.7 s). |
| **G4** | NOT VERIFIED BY ME | `G4/roles-sheet.png` | On disk; the verdict is RC's Q4. |
| **T1.1** | NOT VERIFIED BY ME | `T1/report-header.png` **now exists**; `T1/cold-read.md` **MISSING** | The input RC needs was produced this pass — the 119-event test now reaches `:1013` and writes it. The answers are RC's and are not written yet. |
| **T1.2** | **PASS** | `T1/vitest.txt` | **2 files, 27 tests green**, one floor / two floors / none. |
| **T1.3** | **FAIL** | `T1/vitest.txt` green, `T1/enum-audit.md`, `R/playwright.txt` | The unit half is green and the audit is on disk, but the criterion is "no raw internal code reaches the run shell's DOM" and one does, in a real browser: `cast.spec.ts:1448` reads the trace's error line as `Run failed: SYNTHETIC_FAILURE: fm_cast_refusal attempt 1…` and `rawCodesIn()` returns `["SYNTHETIC_FAILURE"]`. `interpret.ts`'s `Run failed: {first sentence}` passes the backend's exception text through unfiltered. The token here is the synthetic injector's own, so the *specific* string is a harness artefact — the *path* is not, and it is the path the criterion is about. |
| **T1.4** | **PASS** | `T1/vitest.txt` | Unknown floor code / dimension key / band still render as words; cases green. |
| **T1.5** | **PASS** | `T1/data-layer-diff.txt`, `R/python.txt` | Both diffs **empty**; `config.py` has no diff at all. Python **2542 OK**. |
| **T2.1** | **FAIL** | `T2/interpretation-vitest.txt` green, `T2/trace-completed.png` **now exists**, `R/playwright.txt` | 66 unit tests green over both real frame logs, and the screenshot the criterion names was finally produced. But the browser assertion the criterion also names fails: **24 of the trace rows read as an empty line** (`cast.spec.ts:1144`, `row 0: empty line` … `row 23`). Round two rebuilt the trace row (compact row, gate person marker, `Run` prefix); the line text the spec reads is now empty for those rows. Both halves of the row are needed and only one holds. |
| **T2.2** | **PASS** | `T2/vocabulary.md` (RV3 section appended twice) | Re-checked. Neither the serializer's ladder nor `frontend/src/trace/` changed in round two — `git diff 27b256e..HEAD` over both prints nothing — and all sixteen `FrameKind` values still have a row. |
| **T2.3** | NOT VERIFIED BY ME | `T2/characters-32px.png`, `T2/originality.md` | On disk with the `.html` that made them; the verdict is RC's Q4. |
| **T2.4** | **PASS** | `CHARACTERS.md`, `G3/vitest.txt` | Green, including the empty-role fallback to the node id. |
| **T2.5** | **PASS** | `T2/no-timers.txt`, `T2/states-32px.png`, `T2/interpretation-vitest.txt` | Re-ran the criterion's grep at `16f3be5`: still **exactly three hits, all in `useRunChoreography.ts`** (`:253` an injectable `now`, `:284` and `:799` the 200 ms arrival receipt), and `frontend/src/characters/` and `AgentCharacter.vue` return **nothing** — which round two could easily have broken, since it added module-level caches and a shared `IntersectionObserver` to that component. |
| **T2.6** | **PASS** | `T2/tie-in.png`, `R/playwright.txt` | `cast.spec.ts:687` passed (3.1 s) in both the cast run and the full suite. |
| **T2.7** | **PASS** | `T2/reduced-motion.png`, `R/playwright.txt` | Both motion tests passed again: `:842` (offscreen, ≤ 12 live animations) and `:881` (reduced motion keeps every `data-state`). |
| **T2.8** | **FAIL** | `T2/perf.json`, `T2/perf-notes.md`, `R/playwright.txt` | **Much better and still short.** Budget: 0 intervals over 34 ms, p95 ≤ 20 ms. Full suite: fixture replay **4 over 34 ms, p95 26.8, max 82.2** (first pass: 15, 32.3, 109.1); live run **5 over 34 ms, p95 19.6, max 79.3** — a p95 inside budget on the live arm. The standalone cast run half an hour earlier measured **34 / 36.3 / 118.5** and **98 / 38.6 / 108.3**, so this number moves a long way with machine load and no single run should be quoted alone. Two things RV3 will not smooth over: the criterion is a hard zero and no run reached it, and `perf.json` still carries only `fixtureReplay` because the live test asserts before it calls `record()`, so its numbers live in the failure message and not in the artifact. |
| **T2.9** | **PASS** | `T2/rowers-grep.txt`, `T2/node-running.png` | Re-captured at `16f3be5` (round two rewrote `WorkflowNode.vue`), by a throwaway spec created, run and deleted, which asserted at the shutter: **0** `.node-crew-oar`, **0** `.node-crew-rower`, **0** `.node-crew-hull`, exactly **1** `[data-testid="node-agent-character"]`. The card read `data-character="market evidence analyst"`, `data-state="working"`. The only `node-rower|node-oar` in all of `frontend/src` is the retirement comment at `node-card.css:210`. |
| **T3.1** | **PASS** | `T3/scope-order.txt` | `SHELL-SCOPE.md` first lands `fcdbadf` 14:09:00; `studio.css` is first touched `fd84f57` 14:25:50. Sixteen minutes fifty seconds. |
| **T3.2** | **PASS** | `T3/literals.txt` | Regenerated verbose: **13 files, 0 colour literals**, 9/9 green. Round two touched six of those thirteen and the inventory is still all zeros. |
| **T3.3** | **FAIL** | `T3/contrast.md`, `T3/contrast-rv3-rerun.txt` | **The gate is now a real gate and one row is left.** W5 removed the owner carve-out: the script counts every row and **exits 1**. Catalogue grew 300 → 330 pairings; sixteen of the first pass's seventeen failures are fixed. The survivor is `light 1.29 < 4.5 — a rail kicker, --accent-cyan on rail, ChatRail.vue:383 / DialogueRail.vue:467 .section-kicker`, owned by W4, with `var(--on-accent-cyan)` named as the fix. The committed `contrast.md` is byte-identical to my re-run (md5 `2f6f1c9fc2f46dfbc826b18ab9fd2eb1`). |
| **T3.4** | **PASS** (artifacts) | `before-*.png` and `after-1440/1180/390/1440-light.png` all present | All four "after" captures now exist — the 119-event test reaches `:982`, `:1021` and `:1039` before it fails, and `after-390.png` comes from the passing 390 px test. The comparison itself is RC's Q6. |
| **T3.5** | **PASS** | `T3/builder-visual.txt` | **16/16 green, 48.9 s, no baseline regenerated** — md5s identical before and after, all sixteen listed in the file. This is the run that matters for T3.5: round two is where `motion.css`, `node-card.css` and `tokens.css` moved. |
| **S1** | **PASS** (artifact) | `S/empty.png` | `cast.spec.ts:507` green; capture re-taken this pass. |
| **S2** | **PASS** | `S/first-run.png` | **Fixed.** `cast.spec.ts:544` passed (18.9 s) in both the cast run and the full suite, and the capture exists. RV1 relaxed the assertion to any non-idle state, which is the honest reading — the synthetic scope node completes instantly and parks at the gate, so "working within two seconds" was never reachable as literally written. |
| **S3** | **PASS** (artifacts) | `S/long-run.png`, `S/long-run.md` | Both now exist: the 119-event test reaches `:990` and `:1090` before its hygiene assertion. The legibility judgement they support is RC's Q7; the row's own artifacts are on disk. |
| **S4** | **PASS** (artifact) / see T1.3 | `S/failure.png` | **The `#idea` clash is fixed** (`textarea#idea`, and the node card no longer lets its id fall through), the test reaches `:1439` and writes the capture, and the failing node does wear the blocked-error character. It then fails at `:1448` on the raw code in the error line, which is recorded against **T1.3** rather than counted twice here. |
| **S5** | **PASS** (artifact) | `T2/reduced-motion.png` | Written by the passing `cast.spec.ts:881`. |
| **S6** | **PASS** | `S/narrow.png`, `R/playwright.txt` | `cast.spec.ts:1192` green (18.5 s) — the `scrollWidth <= 390` assertion. |
| **R1** | **FAIL** | `R/python.txt`, `vitest.txt`, `typecheck.txt`, `build.txt`, `playwright.txt`, `baselines.md` | Four suites green (2542 / 1936 / exit 0 / exit 0); Playwright **155 passed, 7 failed, 0 skipped**. Baselines: the third and last one regenerated and named; all three now named with reasons. Breakdown in section 3. |
| **R2** | **PASS** | `R/diff-stat.txt` | Three Python source files and no more: `builder/descriptor.py` (the amended-allowed one), `service/runner.py`, `service/builder_runner.py`, plus four test modules. The four forbidden surfaces are each printed on their own line as **NO DIFF**: `validator_flow.py`, `schemas/`, `validator_guardrails.py`, `config.py`. Round two added no Python at all. |

## 3. The seven Playwright failures

**Two are the item-44 drag flake, and both were re-run alone once and passed.**
`builder.spec.ts:1227` (target handle green/red, 2.8 s) and `builder.spec.ts:1552`
(attach a tool by dragging its port, 2.6 s). Declared rather than folded in.

**Two are the frame budget** — `cast-perf.spec.ts:315` and `:460`. See T2.8:
much improved, still not zero, and noisy enough that the run-to-run spread
(4–34 over-budget intervals for the same 131 frames) is itself part of the
finding.

**Two are `cast.spec.ts`'s content assertions**, each of which the test now
reaches only because round two fixed everything in front of it: 24 empty trace
rows (T2.1) and `SYNTHETIC_FAILURE` in the error line (T1.3).

**One is `visual/run-canvas.spec.ts:204`, and it is the interesting one.** It is
not a screenshot failure — `toHaveScreenshot('run-canvas-idle.png')` at `:207`
passes. It fails at `:243`:

```
Expected: "rgb(179, 179, 179)"     // --text-muted, what .node-state gives
Received: "rgba(255, 255, 255, 0.52)"   // --text-meta, dark
```

The spec's own comment says `.quarantine-count` and `.node-state` sit on the
same element at the same specificity and that `.node-state` wins only by being
written later, so **both rules must move together**. Round two added
`.studio-shell:not(.is-builder) .quarantine-count { color: var(--text-meta) }`
to `motion.css:392-397` as part of the contrast work. That selector outranks
both, so the quarantine chip took a colour its twin did not — the exact
divergence the test exists to catch, arriving through a door the comment did not
anticipate. Full trace in `R/baselines.md`.

## 4. What round two demonstrably fixed, measured rather than taken on trust

| First pass (`27b256e`) | Second pass (`16f3be5`) |
| --- | --- |
| `studio.spec.ts:204` and `:351` red on the sentence-cased gate labels | both **PASS** |
| `run-canvas.spec.ts` "branch in flight" timed out on `.node-crew-oar` | **PASS**, and its baseline is finally regenerable |
| S2: no working character within 2 s | **PASS** |
| The Revise reply the gate card never took | **PASS** (`e2e/gateReply.ts` keys on the gate node's pass count) |
| S4: `#idea` resolved to two elements | **PASS** |
| 17 of 300 contrast pairings below AA, script exiting 0 | 1 of 330, script exiting **1** |
| 7 DoD artifacts missing | **0 missing** except the two RC owns |
| perf: 15 over 34 ms, p95 32.3 | 4 over 34 ms, p95 26.8 (fixture); 5 and 19.6 (live) |
| 9 Playwright failures | 7, of which 2 are a known flake that passes alone |

## 5. Things a reader should know that no criterion asks for

1. **`benchmarks/perf/canvas.json` is modified in the working tree**, by
   `e2e/builder-perf.spec.ts`, which rewrites it on every full run. A suite
   side-effect, not an edit; left as the suite wrote it.
2. **T2.8's live measurement is not in its artifact.** `cast-perf.spec.ts:448`
   asserts before `record()`, so `perf.json` carries only `fixtureReplay` and
   the live arm's numbers exist only in the failure text. Whoever fixes the
   budget should move the `record()` call above the assertions, or the artifact
   will keep describing half the criterion.
3. **The perf numbers are load-sensitive to a degree that matters.** The same
   131-frame replay measured 4 over-budget intervals in the full suite and 34 in
   a standalone run twenty minutes earlier on the same machine, same backend,
   same commit. RV2 was capturing G1 concurrently for part of this session. The
   verdict does not turn on it — no run reached zero — but a future
   "it passes now" needs more than one run to mean anything.
4. **`builder_runner.py` is a second synthetic double.** R2's wording is
   singular; there are two (`service/runner.py::SyntheticValidatorRunner` and
   `service/builder_runner.py::_SyntheticCrew`), and both changes are the same
   change: an `agent_role` stamped on the frames a free run emits. Read as
   within R2; flagged so it is said rather than inferred.
5. **The Python suite makes a live Pinecone `describe_index` call** with `.env`
   present. Read-only, free, and pre-existing — but the suite is not
   network-free on this machine.
6. **Tally: 22 PASS, 5 FAIL, 4 NOT VERIFIED BY ME** over the 31 rows.
   First pass was 19 / 8 / 4.

---
---

# FIRST PASS — `27b256e`, 2026-09-05

Kept verbatim below, because round two's repairs are only legible against what
this pass found. Where the two disagree, the second pass is current.

Written by **RV3**, a verification worker, on branch `run-shell/cast` at
`27b256e`, 2026-09-05, in the main tree `D:\MultiAgentSystem` on Windows 11.

RV3 built none of this work and edited no product code. The one product-tree
change RV3 is permitted, and made, is regenerating two of the three PNGs under
`frontend/e2e/visual/run-canvas.spec.ts-snapshots/`, after first recording the
failing diff — [`evidence/R/baselines.md`](R/baselines.md).

`G1`, `G4`'s sheet and every `RC` row belong to other workers and are marked
**NOT VERIFIED BY ME**. A missing artifact is recorded as **FAIL**, not as a
pass with a note.

---

### 1. What was run, and against what

| | |
| --- | --- |
| Python | `.\.venv\Scripts\python.exe -m unittest discover -s tests -t .` — **2542 tests, OK, 6 skipped, 131.5 s**, exit 0 |
| Vitest | `npx vitest run` from `frontend/` — **92 files, 1926 tests, 0 failed** |
| Types | `npx vue-tsc -b --force` — **exit 0**, no diagnostics |
| Build | `npm run build` (`vue-tsc -b && vite build && tsc -p tsconfig.server.json`) — **exit 0**, built in 706 ms |
| E2E | `npx playwright test`, both projects — **162 tests: 153 passed, 9 failed, 0 skipped, 13.1 m**, exit 1 |

Backend, started from the repo root in the background, its log read rather than
`/healthz` trusted:

```
SYNTHETIC=1  SYNTHETIC_BRANCH_DELAY_SECONDS=5  PORT=8099
CREDENTIALS_MASTER_KEY=Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE=
BUILDER_ALLOW_GATELESS_GRAPHS=1
RUN_RATE_LIMIT_MAX_RUNS=100            (.agent/MISSION.md section 8)
MCP_ALLOW_INSECURE_LOCAL=1             (.agent/MISSION.md section 8)
SKILLS_ROOT=D:/MultiAgentSystem/data/skills
SYNTHETIC_FAILURE="fm_bad_key:bad_key:1,fm_tool_timeout:tool_timeout:1,
                   fm_refusal:refusal:1,fm_malformed:malformed_output:1,
                   fm_rate_limit:rate_limit:1,fm_cast_refusal:refusal:1"
./.venv/Scripts/serve.exe
```

**The `SYNTHETIC_FAILURE` value is the two files' strings combined**, which the
grammar allows: `builder_runner.py::parse_synthetic_failures` splits on commas
and every entry carries its own node prefix. The first five entries are
`e2e/failure-modes.spec.ts`'s header; the sixth is `e2e/cast.spec.ts`'s S4.
Every node named is one only those two files author, so one backend serves the
whole suite. The MCP fixture (`tests/service/mcp_fixture_server.py`,
`build_server(port=8791)`, streamable-http) ran with `E2E_MCP_URL` exported, so
`builder-mcp.spec.ts` ran rather than skipping — which is why the suite reports
**0 skipped**.

Money spent: **zero**. Nothing was ever pointed at :8000.

**The backend really was this branch's code**, proved rather than assumed. On
`main`, `descriptor.py` sets a node's `agent_role` from `agent_id`, which an
*authored* agent does not carry, so `main` answers `null` for one. A throwaway
authored graph published against :8099 answered:

```
idea |agent_role= None
a1   |agent_role= 'Probe evidence analyst'      <- this branch's node_agent_role()
out  |agent_role= None
```

The probe graph was unpublished and deleted straight afterwards.

---

### 2. The table

| Id | Verdict | Evidence | What RV3 saw |
| --- | :---: | --- | --- |
| **G1** | NOT VERIFIED BY ME | `evidence/G1/` | RV2's, and complete on disk: `invented-flow.json`, `graph.png`, `trace.png`, `run.ndjson`, `notes.md` naming freeze commit `6833089` and the run. RV3 did not touch G1 or port 8098. |
| **G2** | **PASS** | `evidence/G2/grep.txt` | The criterion's exact grep over `frontend/src/characters`, `frontend/src/trace`, `AgentCharacter.vue`, `useRunChoreography.ts`: **one hit, zero product hits**. The hit is `useRunChoreography.ts:137`, the last line of `readsAsRole()`'s JSDoc, quoting `Scoper` as an *example* of a one-word role that passes on its capital. The function body is three lines of `/\s/` and `/[A-Z]/` and holds no role list. Judged and written down in the file. |
| **G3** | **PASS** | `evidence/G3/vitest.txt`, `evidence/G3/playwright.txt`, `evidence/G3/reload-map.json` | `characterSystem.spec.ts` + `characterDeterminism.spec.ts`: **2 files, 69 tests, all passed**, asserting a committed 20-role snapshot (`frontend/tests/fixtures/characterSnapshots.json`, tracked) generated in one process and asserted in another. The Playwright reload check passed in both runs (`cast.spec.ts:756`, 15.3 s), and `reload-map.json` records the node-to-seed map before and after the reload. |
| **G4** | NOT VERIFIED BY ME | `evidence/G4/roles-sheet.png` | On disk and refreshed today with the G1 roles; the verdict is RC's section 6 Q4, which is not written yet. |
| **T1.1** | NOT VERIFIED BY ME | `evidence/T1/report-header.png` **MISSING**, `evidence/T1/cold-read.md` **MISSING** | RC's row, but its input does not exist: the PNG is written by `cast.spec.ts:991`, inside the 119-event test that failed (row R1 below). Nothing for RC to read. |
| **T1.2** | **PASS** (spec half) | `evidence/T1/vitest.txt` | `verdictDisplay.spec.ts` + `noRawCodes.spec.ts`: **2 files, 27 tests, all passed**, covering a fixture verdict with one floor, two floors and none. W5 owns the review of the spec; RV3 owns that it runs and is green. The PNG half of the row is blocked with T1.1. |
| **T1.3** | **PASS** (spec + audit half) | `evidence/T1/vitest.txt`, `evidence/T1/enum-audit.md` | `noRawCodes.spec.ts` green over the verdict and gate fixtures; the audit is on disk and lists every site with its disposition and owner. Verifier of record is W5. |
| **T1.4** | **PASS** | `evidence/T1/vitest.txt` | The unknown-code fallback cases are in `verdictDisplay.spec.ts` and green. |
| **T1.5** | **PASS** | `evidence/T1/data-layer-diff.txt`, `evidence/R/python.txt` | `git diff main...HEAD --stat` over `src/brief_crew/schemas`, `validator_guardrails.py`, `validator_flow.py` is **empty**; `git diff main...HEAD -- src/brief_crew/config.py \| grep -E "RUBRIC\|FLOOR\|CONFIDENCE"` is **empty**, and `config.py` has no diff at all. Python suite **2542 OK**. |
| **T2.1** | **FAIL** | `evidence/T2/interpretation-vitest.txt` green; `evidence/T2/trace-completed.png` **MISSING** | `traceInterpretation.spec.ts` + `characterStates.spec.ts`: **2 files, 66 tests, all passed** over both committed frame logs, and `serializerFrames.ndjson` / `syntheticRun.ndjson` are tracked. The screenshot the criterion names is written by `cast.spec.ts:967`, inside the test that failed. Half the evidence exists; the criterion asks for both. |
| **T2.2** | **PASS** | `evidence/T2/vocabulary.md` (RV3's section appended), `evidence/G2/grep.txt` | Checked the table against `serializer.py::_event_drafts` branch by branch and against `registry.py`'s own frames. **All sixteen `FrameKind` values have a row and every `stage` the serializer writes is named.** Three things worth knowing are recorded in the appendix: the nested-flow frames are `AGENT` and land on the three `agent` rows; `LLMCallCompletedEvent` produces three frames, all three rowed; `guardrail` has no error stage because the serializer has no such branch. |
| **T2.3** | NOT VERIFIED BY ME | `evidence/T2/characters-32px.png`, `evidence/T2/originality.md` | Both on disk with the `.html` that produced them and a re-runnable script. The verdict is RC's section 6 Q4. |
| **T2.4** | **PASS** | `docs/run-shell/CHARACTERS.md`, `evidence/G3/vitest.txt` | The design note is on disk; `characterSystem.spec.ts` is green and covers one-word-apart roles differing, the same role twice being identical, and an empty role falling back to the node id and still drawing every part. |
| **T2.5** | **PASS** | `evidence/T2/states-32px.png`, `evidence/T2/no-timers.txt`, `evidence/T2/interpretation-vitest.txt` | RV3 re-ran the criterion's grep at HEAD and got **exactly the three hits W4 recorded, at the same line numbers**: `useRunChoreography.ts:236` (an injectable `now` default), `:256` and `:744` (the 200 ms arrival-receipt pulse). `frontend/src/characters/` and `AgentCharacter.vue` return nothing, which is the half that matters. `characterStates.spec.ts` derives every state from fixture frames and is green. |
| **T2.6** | **PASS** | `evidence/T2/tie-in.png`, `evidence/R/playwright.txt` | `cast.spec.ts:665` — "mid-run, every running node and its trace rows carry one seed and agree on the state" — **passed in both runs** (3.1 s), and the capture is on disk. |
| **T2.7** | **PASS** | `evidence/T2/reduced-motion.png`, `evidence/R/playwright.txt` | Both motion tests passed in both runs: `cast.spec.ts:820` (nothing animates offscreen, at most twelve live character animations) and `cast.spec.ts:859` (reduced motion stops every part and keeps every `data-state`). Capture on disk. |
| **T2.8** | **FAIL** | `evidence/T2/perf.json` | The artifact exists and **reports a miss, twice, on two independent runs**. The budget is 0 intervals over 34 ms and p95 at most 20 ms. Measured: **15 intervals over 34 ms** (6 of them over 50 ms), **p95 32.3 ms, max 109.1 ms** over 131 frames — and 15 / p95 31.2 / max 111.3 on the earlier standalone run. `e2e/cast-perf.spec.ts:440` fails on its own assertion and says so in one sentence. The second measurement (`liveSyntheticRun`) is absent from the file because `cast-perf.spec.ts:311` failed at a gate before it could be taken. |
| **T2.9** | **PASS** | `evidence/T2/rowers-grep.txt`, `evidence/T2/node-running.png` | The criterion's grep over `WorkflowNode.vue` returns nothing; RV3 also grepped all of `frontend/src` for `node-rower\|node-oar` and got **one hit, a comment in `assets/styles/node-card.css:210` recording the retirement**. `node-running.png` did not exist — no committed spec writes it — so RV3 captured it with a throwaway spec (created, run, deleted, never committed) which also asserted at the shutter that the running card has **0** `.node-crew-oar`, **0** `.node-crew-rower`, **0** `.node-crew-hull` and exactly **1** `[data-testid="node-agent-character"]`. That card's `.pip` read `data-character="market evidence analyst"`, `data-state="working"`. |
| **T3.1** | **PASS** | `evidence/T3/scope-order.txt` | Regenerated. `SHELL-SCOPE.md` first lands in `fcdbadf` at **14:09:00**; `frontend/src/studio.css` is first touched on this branch in `fd84f57` at **14:25:50**. The scope was proposed sixteen minutes before the first shell edit. |
| **T3.2** | **PASS** | `evidence/T3/literals.txt` | Regenerated with `--reporter=verbose`, because the inventory the spec prints *is* the evidence. **13 files scanned, 0 colour literals in any of them**, 9/9 tests green — including "anywhere on the branch", which was RED by design in W5's copy at `40e17dc` while W1 and W3 still held their files open. `docs/design.md` section 2 names the seven type roles and section 3 the space, radius and elevation tokens. Verifier of record is W3. |
| **T3.3** | **FAIL** | `evidence/T3/contrast.md`, `evidence/T3/contrast-rv3-rerun.txt` | The script re-runs clean and its `--markdown` output is **byte-identical** to the committed file (md5 `358394a1099e54059400f734602b8d79`), so nothing was copied. But the criterion is "every text/background pairing… at least 4.5:1 / 3:1, in both themes", and **17 of the 300 pairings do not meet it** — 1 W1, 3 W3, 13 W4, mostly in the light theme, worst 1.02:1 on a crew pip. The script's exit 0 counts W5's 80 rows only, by an explicit and sound design decision that is not the criterion. The seventeen are listed in full in the re-run note. |
| **T3.4** | **FAIL** | `before-*.png` all present; `after-390.png` present; **`after-1440.png`, `after-1180.png`, `after-1440-light.png` MISSING** | The three missing captures are written by `cast.spec.ts:960`, `:999` and `:1017`, inside the 119-event test that failed before reaching them. RC cannot answer section 6 Q6 without the 1440 pair. |
| **T3.5** | **PASS** | `evidence/T3/builder-visual.txt` | Re-run at the branch head: **16/16 passed, 45.9 s**, and the sixteen baseline md5s are identical before and after, so **no baseline was regenerated**. The file carries all sixteen sums. |
| **S1** | **PASS** (artifact) | `evidence/S/empty.png` | `cast.spec.ts:515` passed in both runs and the capture is on disk. The reading of it is RC's Q7. |
| **S2** | **FAIL** | `evidence/S/first-run.png` **MISSING** | `cast.spec.ts:552` failed in both runs with *"no character reached `working` within 2s of Launch"*, and the backend **did** carry `SYNTHETIC_BRANCH_DELAY_SECONDS=5`. RV3 reproduced the mechanism independently: on the synthetic validator the scope node completes instantly and the run parks at the scope gate, so no node is `is-running` at all until the gate is answered — a throwaway capture waited 90 s after Launch and never saw one, then saw one immediately after Approve. Whether that is a product gap (nothing says "working" in the first two seconds) or a false premise in the criterion is the orchestrator's judgement; either way there is no artifact. |
| **S3** | **FAIL** | `evidence/S/long-run.png` **MISSING**, `evidence/S/long-run.md` **MISSING** | Same failing test. It fell over inside `reviseGate()`: after clicking **Revise** on the scope gate, `.gate-card` never reached count 0 in 60 s. The page snapshot shows the revise really happened — a "Revise scope here…" line is in the dialogue rail — and the gate simply re-opened faster than the assertion could observe the gap. |
| **S4** | **FAIL** | `evidence/S/failure.png` **MISSING** | `cast.spec.ts:1363` failed in both runs on `locator('#idea')` **resolving to two elements**: the idea `<textarea id="idea">` and an `<article id="idea">` workflow node. The failure graph names its input node `idea`, and Vue Flow's node id falls through to the card's DOM `id` because `WorkflowNode.vue` sets no `inheritAttrs: false` — which is true on `main` too, so the product behaviour is pre-existing and the new spec is the first thing to meet it. Either end is a fix; neither is RV3's to make. |
| **S5** | **PASS** (artifact) | `evidence/T2/reduced-motion.png` | Written by the passing `cast.spec.ts:859`. The reading is RC's Q7. |
| **S6** | **PASS** | `evidence/S/narrow.png`, `evidence/R/playwright.txt` | `cast.spec.ts:1170` — "a run drives and finishes at 390px, and nothing overflows sideways" — **passed in both runs** (18.5 s), which is where the `scrollWidth <= 390` assertion lives. Capture on disk. |
| **R1** | **FAIL** | `evidence/R/python.txt`, `vitest.txt`, `typecheck.txt`, `build.txt`, `playwright.txt`, `baselines.md` | Four of the five suites are green: Python **2542 OK / 6 skipped**, Vitest **1926 passed / 92 files**, `vue-tsc -b --force` **exit 0**, `npm run build` **exit 0**. Playwright is **153 passed, 9 failed, 0 skipped**. Baselines: two regenerated and named with a reason; the third could not be, and that is one of the nine. Breakdown in section 3. |
| **R2** | **PASS** | `evidence/R/diff-stat.txt` | Three Python source files change on this branch and no more: `builder/descriptor.py` (the amended-allowed one — `node_agent_role()` replacing `getattr(node.config, "agent_id", None)`), `service/runner.py` and `service/builder_runner.py`. Nothing else under `src/brief_crew/builder/`; no `validator_flow.py`, no `schemas/`, no guardrails, and no diff to `config.py` at all. Four Python test modules. See note 2 in section 4 on `builder_runner.py`. |

---

### 3. The nine Playwright failures, sorted by what they mean

**Three are a spec the work contradicted and nobody updated.** These are honest
reds about the product having changed on purpose:

| test | what it asserts | what shipped |
| --- | --- | --- |
| `visual/run-canvas.spec.ts:249` | `.node-crew-oar` / `.node-crew-rower` / `.node-crew-hull` run their keyframes on a running card, at `:305-310` and again at `:328` | T2.9 removed all three. The locator times out after 15 s and the test never reaches its `toHaveScreenshot('run-canvas-running.png')`, which is exactly why that third baseline could not be regenerated. |
| `studio.spec.ts:224` | the scope gate's five field labels read `startup idea`, `category`, `target user`, `market query`, `feedback` | T1 sentence-cased them: `Startup idea`, `Category`, `Target user`, `Market query`, `Feedback`. **Case only** — five expected, five received, same words in the same order. |
| `studio.spec.ts:371` | the verdict gate's derived keys are `verdict`, `confidence`, `cheapest next test` | now `Verdict`, `Confidence`, `Cheapest next test`, **`Scope reply`** — sentence case again, plus one new derived key. |

**Two are the frame budget, and they are a measurement rather than a flake.**
Both `cast-perf.spec.ts` tests failed in both runs, and the fixture replay's
numbers agree to within a millisecond across two independent runs on a machine
the script itself measured at 60.2–60.6 Hz. See T2.8.

**Three are `cast.spec.ts`'s own**, each reproduced in both runs: S2's
two-second working character, the Revise reply the gate card never appeared to
take, and the duplicate `#idea` DOM id. Detailed in the S rows above.

**One is the known flake.** `builder.spec.ts:1227` (`paints the target handle
green when it will take the edge and red when it will not`) failed on a
`locator.hover` timeout — the drag-test class CLAUDE.md remaining-work item 44
already records. **RV3 re-ran it alone once and it passed in 2.8 s.** Recorded
here because a re-run that is not declared is not evidence.

---

### 4. Things a reader should know that no criterion asks for

1. **`benchmarks/perf/canvas.json` is modified in the working tree**, by
   `e2e/builder-perf.spec.ts`, which rewrites it on every full run. It is a
   suite side-effect, not an edit — RV3 changed no product file other than the
   two baselines. It is left exactly as the suite wrote it.
2. **`builder_runner.py` is a second synthetic double.** R2's wording says "the
   only other Python change is the synthetic double's identity fields and its
   tests", singular. There are two:
   `service/runner.py::SyntheticValidatorRunner` (the validator) and
   `service/builder_runner.py::_SyntheticCrew` (a published graph). Both changes
   are the same change — an `agent_role` stamped on the frames a free run emits,
   so the free path carries the field the paid path already did. Read as within
   R2; flagged so the orchestrator can say so rather than infer it.
3. **The Python suite makes a live Pinecone `describe_index` call.**
   `api.pinecone.io/indexes/agentic-crew-ai-index -> 200` appears in the run at
   14:55:40. Read-only and free, and pre-existing rather than anything this
   branch did, but it means the suite is not network-free with `.env` present.
4. **T3.4's three missing captures are one red away.** They are taken in
   `cast.spec.ts:941` *after* the 119-event run completes, and the test dies
   earlier, at the first Revise. Repair `reviseGate`'s gap assertion (or the
   reopen it races) and all three arrive together with
   `T1/report-header.png`, `T2/trace-completed.png`, `S/long-run.png` and
   `S/long-run.md`. **Seven missing artifacts, one failing test.**
5. **Tally: 19 PASS, 8 FAIL, 4 NOT VERIFIED BY ME**, over the 31 rows of the
   definition of done's five tables (G1–G4, T1.1–T1.5, T2.1–T2.9, T3.1–T3.5,
   S1–S6, R1–R2). Eight FAILs, but not eight independent problems: four of them
   (T2.1, T3.4, S3 and — for its captures — T1.1's input) are the single failing
   `cast.spec.ts:941`, and R1 is the roll-up of everything else.
