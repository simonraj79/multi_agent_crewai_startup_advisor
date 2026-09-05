# RV3 — verification report

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

## 1. What was run, and against what

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

## 2. The table

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

## 3. The nine Playwright failures, sorted by what they mean

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

## 4. Things a reader should know that no criterion asks for

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
