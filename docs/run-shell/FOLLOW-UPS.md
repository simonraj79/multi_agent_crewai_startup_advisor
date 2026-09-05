# Follow-ups — found during the run-shell work, deliberately not done here

Each line is something the brief did not name, or names a surface the brief put
out of scope (flow-specific rendering, the workflow engine, the scoring system,
the builder workspace). Recorded with where it was found. None is a defect this
branch introduced.

## Deferred token VALUE changes (Option A ruling, 2026-09-05)

The audit in `SHELL-SCOPE.md` measured four token values whose correction moves
the builder's committed pixel baselines. They were left as-is so T3.5 could hold
without a regeneration; each is one commit once the builder baselines are due a
refresh anyway.

- `--border-hover` and `--warn-border` / `--err-border`: below 3:1 as UI borders in the light theme.
- Light `--link-cyan` on the pale accents used as small text (`tokens.css` records this itself).
- Light `--surface-well` equals `--surface-raised`, so the three-level surface system is two in light.
- `node-card.css`: five `--text-40` sites at 4.31:1 in light want `--text-meta`; shared with the builder card.

## Shell

- Gate card field values are `<input>`s and cannot wrap; a sentence-long value ("STARTUP IDEA", "MARKET QUERY") ellipsises at 346 px in the narrow drawer. A `<textarea>` is the right element and moves two assertions that count inputs (`tests/gateDerived.spec.ts`, `e2e/studio.spec.ts`).
- The 52 px header against the 64 px panel rhythm (`studio.css:129`, `:171`); moving it changes `.validator-flow`'s height and every run-canvas baseline.
- `capture-run.spec.ts` switches themes with `emulateMedia` alone, so its `*-light-*.png` captures are dark pixels under a light filename; the run shell reads `data-theme`.
- Run status is rendered three ways (`StudioView.vue`, `StatusPanel.vue`, `RunHistory.vue`); two now use `runStatusDisplay.ts`, the status-panel connection labels do not.

## Data layer (out of scope by the brief; the display now reads it honestly)

- `decision_reason` and `fatal_floors` are computed independently in `schemas/validator.py:538-566`; a floor can be listed while the low-confidence branch decides. The display is keyed on `decision_reason` and says so; whether a listed-but-not-deciding floor should exist at all is a rubric question.
- Dimension display names exist only in `validator_flow.py::_DIMENSION_LABELS` and now again in `frontend/src/data/verdictDisplay.ts`; the API does not expose them. A `dimensions` block on the verdict frame carrying `label` and `question` would remove the client mirror.
- `provisional` covers `INSUFFICIENT_EVIDENCE` (CLAUDE.md §4's unratified deviation) — unchanged, still open.

## Trace and cast

- Builder nodes carry no `task_name` because `builder/runtime.py:910` builds the Task with no `name`; the trace therefore cannot say which task an authored agent is on. Naming the task from the node label at compile time is a one-line runtime change.
- A crew node (many agents) has no single role; it renders as the crew's label with a character seeded on that label. A per-member cast needs member frames the serializer does not emit.
- Gate titles on builder graphs fall back to ids like `n1_confirm` (title-cased, so they evade the raw-code regex). The compiler should carry the author's gate label into the gate frame.
- `useValidatorRun.recoverIdea` reads `details.inputs.idea` by name rather than the workflow's `inputField` (latent for builder graphs; found by the boundary map).
- The synthetic double still emits `node_state` for step nodes the real serializer would not attribute the same way; the trace hides them by kind, which rests on the descriptor's `kind` being right.

## Found by authoring the G1 flow (RV2, 2026-09-05)

- `builder/descriptor.py` drops attachment nodes from `nodes` but builds `edges` from `document.edges` unfiltered, so a tool attachment ships as a dangling edge and Vue Flow logs `Edge source or target is missing` on every render of the run canvas. A `warn`, so the zero-console-errors rule does not see it. Fix: filter `edges` on `target_port == "in"`, the predicate the same function already uses for `incoming`.
- The gate's operator-facing `summary` says "Reply with JSON: decision=approve" while `GateReplyRequest` takes `outcome` and is `extra="forbid"`, so following the on-screen instruction over HTTP is a 422. The browser path is unaffected.
- The synthetic builder runner has no per-node delay (`SYNTHETIC_BRANCH_DELAY_SECONDS` paces only the validator's branches), so a published graph's post-gate half completes in under a second and a mid-run capture needs socket throttling.

## Performance (measured 2026-09-05, `evidence/T2/perf-notes.md`)

- Headless Chromium on this machine rasterises with SwiftShader, and `backdrop-filter` costs a full re-blur of everything behind each surface per frame. The run shell's four blurs are removed; the builder workspace still uses `--blur-panel` / `--blur-rail` on its rails and palette and was not measured — the same bisect would say whether it should keep them.
- The replay harness (`page.routeWebSocket` + CDP) drops ~17 frames per 131 with nothing painted; a harness that feeds frames from inside the page (a worker or a scripted socket) would measure the console more tightly.
- The `run_state` frames' `result` and every `details` payload reach the trace disclosure in full; a lazy `<details>` body would halve the DOM per row but `traceInterpretation.spec.ts` deliberately asserts the payload is present while closed.

## The synthetic double's prose (found by the cold readers)

- `service/runner.py`'s `_SYNTHETIC_UTTERANCE` splices the idea into the sentence without quotes ("I read A claim auditor that checks…") and every branch says the same sentence, so the dialogue rail on a synthetic run reads as four identical entries. Quote the idea and vary the template per branch; it is the double's text, not the console's.
- RV2's mid-run G1 capture throttles the socket and re-launches on a rate-limit retry, so the trace can pool two runs ("Run started" twice) while the graph shows one — a capture-method artefact recorded in `evidence/G1/notes.md`, not a product state.

## Builder workspace (LEAVE)

- `e2e/builder.spec.ts:1227` ("paints the target handle green/red") fails **on `main` too** — 4 of 5 runs at `6291fee`, identical failure shape (`evidence/R/builder-1227.md`): the attach port resolves and is stable, then the problems dock's `problem-message` intercepts the hover for the full 15 s. It is an occlusion, not a timing flake, and it is not the case CLAUDE.md item 44 describes (that one passes alone; this fails alone). Fix is in the dock's layout or the test dismissing the dock first; neither is on this branch.

- The builder's `.segmented` had no base rule and rendered as native buttons in its header; the promoted global is guarded off the builder so its baselines stayed green. Lifting the guard is a builder change with a baseline regeneration.
