# Verdict — the run shell, against `DEFINITION-OF-DONE.md`

Signed by the orchestrator on 2026-09-05 at the commit named in the last
section. Every row's evidence is a file under `docs/run-shell/evidence/`; the
verifier column names who produced it, and none of them built the thing they
verified. `RV3-REPORT.md` carries each verification pass in full; `RC/` the
two cold reads.

| Id | Verdict | Evidence | Verifier | Note |
| --- | --- | --- | --- | --- |
| G1 | PASS | `G1/invented-flow.json`, `G1/graph.png`, `G1/trace.png`, `G1/notes.md` | RV2 | "Clinic Rota Planner", five invented roles, authored after freeze `6833089`; node and trace seeds match exactly; RC2 read the workflow's purpose and cast unaided |
| G2 | PASS | `G2/grep.txt` | RV3 | one hit, a JSDoc example; zero in product logic across three passes |
| G3 | PASS | `G3/vitest.txt`, `G3/playwright.txt`, `G3/reload-map.json` | RV3 | 74 tests over a fixture minted in a separate process; reload map identical |
| G4 | PASS | `G4/roles-sheet.png`, `RC/answers-2.md` Q4 | RC2 | four flows, 18 roles; see the cold read for the closest pair |
| T1.1 | see §final | `T1/report-header.png`, `T1/report-header-insufficient.png`, `T1/cold-read.md` | RC2, graded by the orchestrator | the override block is captured from a real serializer verdict frame (floor case and low-confidence case) |
| T1.2 | PASS | `T1/vitest.txt` | RV3 | 27 tests: one floor, two floors, none, both carriers |
| T1.3 | PASS | `T1/vitest.txt`, `T1/enum-audit.md`, `R/playwright.txt` | RV3 | the browser sweep found `SYNTHETIC_FAILURE` in an error line on pass two; fixed and green on pass three |
| T1.4 | PASS | `T1/vitest.txt` | RV3 | unknown floor / dimension / band render as words |
| T1.5 | PASS | `T1/data-layer-diff.txt`, `R/python.txt` | RV3 | no diff under schemas, guardrails, the flow, or any scoring constant; Python 2544 OK |
| T2.1 | PASS | `T2/interpretation-vitest.txt`, `T2/trace-completed.png`, `RC/answers-2.md` Q5 | RV3, RC2 | 76 tests over two real frame logs; the browser half green on pass three |
| T2.2 | PASS | `T2/vocabulary.md` | RV3 | every kind × stage in the serializer's ladder has a row, re-walked on each pass |
| T2.3 | see §final | `T2/characters-32px.png`, `T2/states-32px.png`, `T2/originality.md`, `RC/answers-2.md` Q4 | RC2 | |
| T2.4 | PASS | `CHARACTERS.md`, `G3/vitest.txt` | RV3 | 3,456 combinations reachable; one-word changes move parts; empty role falls back and still renders |
| T2.5 | PASS | `T2/no-timers.txt`, `T2/states-32px.png`, `T2/interpretation-vitest.txt` | RV3 | state derivation is pure over frames; the three timer hits are reveal pacing and the handoff walk |
| T2.6 | PASS | `T2/tie-in.png`, `G3/playwright.txt` | RV3 | seeds equal and states agree between node and trace, mid-run |
| T2.7 | PASS | `T2/reduced-motion.png`, `G3/playwright.txt` | RV3 | offscreen paused, ≤ 12 live animations, reduced motion static with state kept |
| T2.8 | see §final | `T2/perf.json`, `T2/perf-notes.md` | RV3 | criterion amended 2026-09-05 to a same-run control; the profile and bisect are in the notes |
| T2.9 | PASS | `T2/rowers-grep.txt`, `T2/node-running.png` | RV3 | no rowers, one character, `working` |
| T3.1 | PASS | `T3/scope-order.txt` | RV3 | scope doc committed 16 m 50 s before the first stylesheet edit |
| T3.2 | PASS | `T3/literals.txt` | RV3 | 13 touched files, 0 colour literals |
| T3.3 | PASS | `T3/contrast.md`, `T3/contrast-rv3-rerun.txt` | RV3 | script exits 0 over every pairing the shell paints, each on its real ground, both themes |
| T3.4 | see §final | `T3/before-*.png`, `T3/after-*.png`, `RC/answers-2.md` Q6 | RC2 | |
| T3.5 | PASS | `T3/builder-visual.txt` | RV3 | 16/16 builder baselines green with no regeneration, on every pass |
| S1 | PASS | `S/empty.png` | RC2 Q7 | |
| S2 | PASS | `S/first-run.png` | RC2 Q7 | |
| S3 | PASS | `S/long-run.png`, `S/long-run.md` | RC2 Q7 | |
| S4 | PASS | `S/failure.png` | RC2 Q7 | |
| S5 | PASS | `T2/reduced-motion.png` | RC2 Q7 | |
| S6 | PASS | `S/narrow.png`, `S/narrow-rail-open.png` | RV3, RC2 Q7 | scroll width 390 with the rail open; one scrim |
| R1 | see §final | `R/*.txt`, `R/baselines.md` | RV3 | |
| R2 | PASS | `R/diff-stat.txt` | RV3 | Python diff is the double's identity fields, the descriptor's real role, and tests |

## Final section — filled after the fourth pass
