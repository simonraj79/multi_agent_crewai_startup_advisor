# Definition of done — the run shell: override wording, the cast, the shell polish

Written 2026-09-05 on branch `run-shell/cast` by the orchestrator, BEFORE any
build began. It is binding: the work is done when every row of the verdict
table in `docs/run-shell/VERDICT.md` is `PASS` with the named artifact on disk
at the named path, checked by the named verifier. An assertion by the builder
is never evidence. A reader who has not seen the build conversation can execute
every check below and reach the same verdict.

Evidence root: `docs/run-shell/evidence/` (PNG allowed there by a `.gitignore`
exception added in this branch). Test results are pasted as text files with
the command that produced them at the top.

## 0. Roles

| Id | Owns (builds) | Must not review |
| --- | --- | --- |
| W1 | Task 1 — verdict display: `ReportPanel.vue`, `data/verdictDisplay.ts`, `GateCard.vue` copy, their specs | T1 |
| W2 | Task 2 — the character system: `components/AgentCharacter.vue`, `src/characters/*`, `assets/styles/character.css`, the sheets | T2.3–T2.5 |
| W3 | Task 2 — the interpretation layer: `src/trace/*`, `ChatRail.vue`, `DialogueRail.vue`, `useValidatorRun.ts`, `types/studio.ts` | T2.1–T2.2 |
| W4 | Task 2 — tie-in and motion: `WorkflowNode.vue`, `useRunChoreography.ts`, `motion.css`, `CrewProgress.vue` medallions, `StudioView.vue` wiring, perf harness | T2.6–T2.9 |
| W5 | Task 3 — tokens and shell chrome: `tokens.css`, `studio.css`, `StatusPanel.vue`, header, `docs/run-shell/SHELL-SCOPE.md` | T3 |
| W6 | Backend honesty + fixtures: `service/runner.py` identity fields, `tests/service`, `frontend/tests/fixtures/*trace*` | G1, T2.1 |
| RV | Verification worker(s): run suites, capture, measure. Never edits product code | — |
| RC | Cold reader: a worker given ONLY screenshots and the questions in §6, no brief, no code | — |

A reviewer is always a worker other than the builder of the thing reviewed.
The orchestrator chooses designs and signs the verdict table; it builds nothing.

## 1. Generalisation (G)

| Id | Criterion | Evidence artifact | Verifier |
| --- | --- | --- | --- |
| G1 | A flow that did not exist when the cast and the interpretation layer were built runs end-to-end in the shell: every agent gets a character, every trace row is an interpreted line, node and trace show the same character. | `evidence/G1/invented-flow.json` (the builder document, authored AFTER the freeze commit named in the file), `evidence/G1/graph.png`, `evidence/G1/trace.png`, `evidence/G1/notes.md` with the freeze commit hash and the run id. | RV, who authors the flow; W2/W3/W4 may not see it before it runs |
| G2 | No source file of the interpretation layer or the character system contains any Idea Validator role, task name, crew name, node id or dimension name. | `evidence/G2/grep.txt`: the exact grep (`Scoper|Market Analyst|Sentiment|Feasibility|Synthesist|Reporter|market_task|scope_idea|research_market|MarketCrew|demand|headroom`) over `frontend/src/characters`, `frontend/src/trace`, `AgentCharacter.vue`, `useRunChoreography.ts` with zero product hits (test fixtures excluded and listed). | RV |
| G3 | Determinism: the same role string yields byte-identical character markup across processes, and the character on a node survives a page reload unchanged. | `frontend/tests/characterDeterminism.spec.ts` (snapshot of the SVG for 20 roles committed as `frontend/tests/fixtures/characterSnapshots.json`, generated in one process and asserted in another run) — result pasted to `evidence/G3/vitest.txt`; Playwright reload check in `e2e/cast.spec.ts` — result in `evidence/G3/playwright.txt`. | RV |
| G4 | Roles from three different flows render as distinct, coherent characters, including a flow invented after the system was built. | `evidence/G4/roles-sheet.png` — Idea Validator (6), Brief Crew (3), and the G1 flow's roles at 32 px and 96 px, dark and light. | RC answers §6 Q4 |

## 2. Task 1 — the override wording (T1)

| Id | Criterion | Evidence artifact | Verifier |
| --- | --- | --- | --- |
| T1.1 | The override block's label is self-explanatory without the paragraph beneath it: a cold reader, given the screenshot alone, correctly states what happened and why the verdict is what it is. | `evidence/T1/report-header.png` (completed run, 1440×900, dark) and `evidence/T1/cold-read.md` — RC's written answers to §6 Q1–Q3, graded by the orchestrator against the mechanic. | RC writes; orchestrator grades |
| T1.2 | The dimension and its score are named in plain language; the evidence chip names dimensions in words; the confidence band and provisional status are words, not codes. | Same PNG; `frontend/tests/verdictDisplay.spec.ts` asserting the rendered text for a fixture verdict with one floor, two floors, and none. Result in `evidence/T1/vitest.txt`. | W5 reviews the spec |
| T1.3 | No raw internal code reaches the run shell's DOM: a rendered report, gate card and status rail contain no token matching `/\b[A-Z][A-Z0-9]+(_[A-Z0-9]+)+\b/` outside an allowlist (run ids, model ids, `NDJSON`/`ZIP`). | `frontend/tests/noRawCodes.spec.ts` over the verdict fixture and the gate fixture; grep audit `evidence/T1/enum-audit.md` listing every site the map found and its disposition. | W5 |
| T1.4 | An unknown floor code, dimension key or band still renders as words (the humaniser fallback), never as SNAKE_CASE. | Cases in `verdictDisplay.spec.ts`. | W5 |
| T1.5 | The data layer is untouched: no diff under `src/brief_crew/schemas/`, `validator_guardrails.py`, `validator_flow.py`, or any `RUBRIC_*` / floor constant in `config.py`; Python suite green. | `evidence/T1/data-layer-diff.txt` (`git diff main...HEAD --stat -- <paths>` empty) and `evidence/R/python.txt`. | RV |

## 3. Task 2 — the cast (T2)

| Id | Criterion | Evidence artifact | Verifier |
| --- | --- | --- | --- |
| T2.1 | Every trace row is one short human-readable line in the user's terms; raw payloads, token counts and JSON sit behind a per-row disclosure collapsed by default; frames that cannot be summarised get no row. Proved over a REAL frame log, not a hand-made one. | `frontend/tests/fixtures/syntheticRun.ndjson` (served by the synthetic backend, byte-for-byte) and `frontend/tests/fixtures/serializerFrames.ndjson` (produced by the real Python serializer over CrewAI events including agent, guardrail and reasoning frames); `frontend/tests/traceInterpretation.spec.ts` asserting for every produced row: ≤ 140 chars, no `\n` literal, no `{"`, no digit-run token count in the line, and that dropped frame kinds produce no row. Result in `evidence/T2/interpretation-vitest.txt`. Screenshot `evidence/T2/trace-completed.png`. | W1 reviews the spec; RC answers §6 Q5 |
| T2.2 | The line vocabulary derives from what CrewAI emits (frame kind, stage, tool name, task name, agent role, model), never from a role list. | G2's grep plus `evidence/T2/vocabulary.md`: the table of frame kind × stage → sentence template, written by W3 and checked by RV against `src/brief_crew/events/serializer.py`'s ladder. | RV |
| T2.3 | Characters are kawaii, original, and legible at 32 px on the dark UI. | `evidence/T2/characters-32px.png` (1× and 3× device scale) and `evidence/T2/originality.md` (W2's part inventory and a statement that no part is traced from or modelled on an existing character). RC's §6 Q4 verdict must say each character is distinguishable at 32 px. | RC |
| T2.4 | The character is compositional and deterministic from the agent's identity: role string → parts, with a coherent result for an unfamiliar role. | `docs/run-shell/CHARACTERS.md` (the system: parts, hash, palette), `frontend/tests/characterSystem.spec.ts` (two roles differing by one word differ in ≥ 1 part; the same role twice is identical; empty role falls back to node id and still renders all parts). | RV |
| T2.5 | Five states — idle, working, speaking, blocked, done — are visibly distinct at 32 px and are driven by run events only. | `evidence/T2/states-32px.png`; `frontend/tests/characterStates.spec.ts` deriving state from fixture frames; `evidence/T2/no-timers.txt` — grep for `setTimeout|setInterval|Date.now` in `src/characters`, `AgentCharacter.vue` and the state derivation in `useRunChoreography.ts`, with every hit explained (reveal pacing is allowed; state is not). | RV |
| T2.6 | The same character appears on the agent's node in the Graph view and in the trace, in the same state at the same moment. | `e2e/cast.spec.ts`: mid-run, for each running node, the `data-character` seed on the node equals the seed on that node's trace avatar, and both carry the same `data-state`. Screenshot `evidence/T2/tie-in.png` showing both views. | RV |
| T2.7 | Motion is continuous but quiet: at most the plan-11 bound of 12 live animations; nothing animates offscreen; reduced motion shows a static pose that still conveys state. | `e2e/cast.spec.ts` assertions: `getAnimations()` on character parts outside the viewport is empty or paused; under `reducedMotion: 'reduce'` every character has `animation-name: none` and a `data-state` still set; `evidence/T2/reduced-motion.png`. | RV |
| T2.8 | No dropped frames at 119+ events — attributable to the console. | `evidence/T2/perf.json`: a Playwright replay of ≥ 119 frames at live pace measuring `requestAnimationFrame` intervals, in THREE arms of one run: (1) the page idle, (2) the same replay with the whole console `visibility: hidden` (the harness's own cost: the socket, the CDP driver, applying the frames), (3) the replay with everything painted. The console passes when arm 3 adds no dropped frames over arm 2 — `over34ms(3) ≤ over34ms(2)` — and `p95(3) ≤ p95(2) + 4 ms`; all three arms' absolute figures are printed. The script is committed as `e2e/cast-perf.spec.ts`. *Amended 2026-09-05 after W4's profile: the first wording (absolute 0 over 34 ms and p95 ≤ 20 ms) measured the machine, not the product — an idle page in headless Chromium on SwiftShader here reads p95 22 ms, and the replay harness alone drops 17 frames with nothing of ours painted. The profile and the bisect are in `evidence/T2/perf-notes.md`; the absolute figures stay in the artifact so a reader can apply the old bar too.* | RV |
| T2.9 | The two-rower crew and the icon medallion are replaced, not duplicated: one cast, no leftover rowers on the node card. | `evidence/T2/node-running.png` and a grep for `node-rower|node-oar` in `WorkflowNode.vue` returning nothing (`evidence/T2/rowers-grep.txt`). The stage lane's validator boat is out of scope and stays. | RV |

## 4. Task 3 — the shell (T3)

| Id | Criterion | Evidence artifact | Verifier |
| --- | --- | --- | --- |
| T3.1 | The scope was proposed before it was built: which surfaces are touched and which left alone, each with a reason. | `docs/run-shell/SHELL-SCOPE.md`, committed before the first shell edit (the file's first commit precedes the first `studio.css` change on the branch — `evidence/T3/scope-order.txt` from `git log`). | RV |
| T3.2 | The improvement flows through tokens: spacing, type-role, elevation tokens exist in `tokens.css`, `docs/design.md` names them, and the touched sheets use them. No hex or `rgba(` literal outside the token sheets in any file touched on this branch. | `frontend/tests/designTokens.spec.ts` (the planned §8 enforcement, scoped to the files on this branch); `evidence/T3/literals.txt`. | W3 |
| T3.3 | WCAG AA throughout: every text/background pairing used by the run shell measures ≥ 4.5:1 (normal text) or ≥ 3:1 (large text, UI components), in both themes. | `evidence/T3/contrast.md` generated by `frontend/scripts/contrast-audit.mjs` (committed), listing pair, ratio, pass. | RV re-runs the script |
| T3.4 | Before/after at three widths: 1440×900, 1180×800, 390×844, dark; and 1440×900 light. | `evidence/T3/before-*.png` and `evidence/T3/after-*.png`. | RC answers §6 Q6 |
| T3.5 | The builder workspace is unchanged by the token work. | Existing `e2e/visual/builder-canvas.spec.ts` passes against its committed baselines — result in `evidence/T3/builder-visual.txt`. | RV |

## 5. The states that are easy to skip (S) and regression (R)

| Id | Criterion | Evidence artifact | Verifier |
| --- | --- | --- | --- |
| S1 | Empty: no run yet — the shell is not blank, the cast shows idle characters on the graph, the trace explains what will happen. | `evidence/S/empty.png` | RC Q7 |
| S2 | First run: within 2 s of Launch, the first working character and the first interpreted line are visible. | `evidence/S/first-run.png` | RC Q7 |
| S3 | Long run: a run of ≥ 119 events — the trace stays legible, the newest line is visible, older rows fold, no layout drift. | `evidence/S/long-run.png` (scrolled to bottom) and the row count in `evidence/S/long-run.md` | RC Q7 |
| S4 | Failure: a failed run shows a blocked/error character on the failing node, one plain-language error line in the trace, and the status rail says failed. | `evidence/S/failure.png` (from `e2e/failure-modes.spec.ts`'s route) | RC Q7 |
| S5 | Reduced motion: state still reads without motion. | `evidence/T2/reduced-motion.png` (shared with T2.7) | RC Q7 |
| S6 | Narrow viewport (390×844): the shell is usable, characters keep legibility, nothing overflows horizontally. | `evidence/S/narrow.png` and the `document.scrollingElement.scrollWidth <= 390` assertion in `e2e/cast.spec.ts` | RV |
| R1 | Suites green: Python `unittest discover`, Vitest, `vue-tsc -b --force`, `npm run build`, full Playwright against `SYNTHETIC=1` on :8099 with zero console errors. Visual baselines regenerated only where this work intentionally changed the pixels, each named. | `evidence/R/python.txt`, `vitest.txt`, `typecheck.txt`, `build.txt`, `playwright.txt`, `baselines.md` | RV |
| R2 | Scope held: the diff touches no file under `src/brief_crew/builder/` except `descriptor.py` (amended 2026-09-05: it now carries the real agent role, because it carried an id or nothing and a user-authored node would otherwise change character at its first frame), and none of `validator_flow.py`, `schemas/`, guardrails, or scoring constants; the only other Python change is the synthetic double's identity fields and its tests. | `evidence/R/diff-stat.txt` | RV |

## 6. The cold reader's questions (RC)

RC receives only the PNGs named above and this list. Answers go to
`evidence/RC/answers.md` verbatim.

1. Looking at `T1/report-header.png` only: what is the verdict, and in one sentence, why is it that verdict rather than what the score suggests?
2. Which dimension caused that, and what did it score?
3. Which dimensions have thin evidence? Name them in words.
4. Looking at `G4/roles-sheet.png`: can you tell the 32 px characters apart? Name two that look most alike and say whether you could still tell them apart. Do any resemble a character you already know from somewhere?
5. Looking at `T2/trace-completed.png`: describe in your own words what the crew did, in order, using only the visible lines.
6. Compare `T3/before-1440.png` and `T3/after-1440.png`: which reads as the more finished product, and what three differences do you notice first?
7. For `S/empty.png`, `S/first-run.png`, `S/long-run.png`, `S/failure.png`, `S/narrow.png`: say in one line each what state the system is in.

Grading: T1.1 passes only if answers 1–3 are correct. G4/T2.3 pass only if
answer 4 says the characters are distinguishable and names no existing
character. T2.1 passes only if answer 5 is a coherent narrative. T3.4 passes
only if answer 6 picks the after.

## 7. Freeze and order

1. W2, W3, W5, W6 and W1 build in parallel with the ownership in §0.
2. When W2 and W3 land, the orchestrator records the FREEZE commit in
   `evidence/G1/notes.md`. RV then authors the invented flow.
3. W4 wires the cast into the node and the trace.
4. RV runs the suites, the captures and the measurements. RC answers §6.
5. The orchestrator fills `VERDICT.md`. Any FAIL goes back to its builder; the
   verdict is re-run, not amended.
