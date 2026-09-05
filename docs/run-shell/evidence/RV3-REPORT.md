# RV3 — verification report

Three passes. **The third, at `601baef`, is the current verdict**; the second
(`16f3be5`) and the first (`27b256e`) are kept below it under their own
headings, because what each round fixed is only legible against what the
previous pass found.

RV3 built none of this work and edited no product code. The one product-tree
change RV3 is permitted, and made, is regenerating the PNGs under
`frontend/e2e/visual/run-canvas.spec.ts-snapshots/` — two in the first pass, one
in the second, all three in the third, each named with a reason in
[`evidence/R/baselines.md`](R/baselines.md) and each after the failing diff was
recorded first.

`G1`, `G4`'s sheet and every `RC` row belong to other workers and are marked
**NOT VERIFIED BY ME**. A missing artifact is recorded as **FAIL**, not as a
pass with a note.

> ### ⚠️ Some artifacts on disk are AHEAD of this report. Read this first.
>
> A fourth, targeted run was begun at **`fec004d`** (the opaque report sheet and
> control rail) and was **called off part-way by the orchestrator**, because
> another fix round was already coming and the run would have been superseded.
> Nothing was reverted — a verifier deleting its own measurements is worse than
> a dated one — so the following files are **fourth-pass measurements at
> `fec004d`** while the table below is the **third pass at `601baef`**:
>
> | file | what it now holds |
> | --- | --- |
> | `T3/contrast.md`, `T3/contrast-rv3-rerun.txt` | the `fec004d` audit: **236 pairings, 234 in scope, 0 failing, exit 0** (pass 3 read 232 / 230 / 0). Still a PASS, by four more rows. |
> | `T3/builder-visual.txt` | the `fec004d` run: **16/16 green, no baseline regenerated**, md5s identical before and after. Still a PASS. |
> | `T1/report-header*.png`, `T2/trace-completed.png`, `T2/tie-in.png`, `T2/reduced-motion.png`, `T3/after-*.png`, `S/*.png`, `S/long-run.md`, `G3/reload-map.json` | rewritten by a `cast.spec.ts` + `studio.spec.ts` run at `fec004d` in which **all 17 tests passed** — including `studio.spec.ts:360`, which is the third pass's stale-copy red. |
>
> Two things that run also established, which the table below therefore
> understates: `e2e/visual/run-canvas.spec.ts` was **green at `fec004d` with no
> regeneration at all** — the sheet and the rail are not inside those three
> crops — and **`studio.spec.ts:360` is fixed**. `e2e/cast-perf.spec.ts` was not
> re-run, so **T2.8's verdict below is still the `601baef` measurement**, and
> every `R/*.txt` except `builder-1227.md` is still the third pass's.
>
> `R/builder-1227.md` is a separate study and stands on its own.

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
