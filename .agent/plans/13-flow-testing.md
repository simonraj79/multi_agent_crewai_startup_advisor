# 13 — Flow testing

Test panel, node-level test, dry run. Written 2026-09-02 against
`25634c0`. Owns no contract; consumes C1, C5, C6, C7, C10.

## Problem

There is no way to run anything from inside the builder. A grep for
`dry.?run|preview|sample input|test panel|single.node` across
`components/builder/`, `composables/useBuilder*.ts` and
`services/builderApi.ts` returns nothing; `builderApi` has seven methods
and none returns code or starts a run (`services/builderApi.ts:339-348`);
`BuilderView.vue:52-57` says in words that no Launch control exists inside
the builder, by rule (`docs/flow-builder-spec.md` R4, cut-list 1) — a rule
whose stated premise, that no `builder_runner` existed, expired in the same
merge (`00-architecture.md` D2). The only path from a canvas to a result is
publish → *Run it* → `sessionStorage` handoff → `StudioView`
(`BuilderView.vue:430-442`), which means an author cannot try a change
without publishing it, cannot try one node, cannot see the state between
steps, and cannot see what their canvas compiled to.

Flowise's answer (`docs/flowise-notes.md` §5) is a chat popover floating
over the graph with an expand-to-modal button, live node badges from one SSE
event, and a resizable execution drawer with Input / Output / State per node
and no per-node timing. That is the bar; R15's *docked, never modal* is the
constraint.

## Scope

A docked test panel with five tabs; saved test inputs per document; a
single-node test with mocked upstream values; a dry run that compiles and
validates without spending a token; the generated-code preview; a state
inspector at every step; the `@launch` cost-tag contract; and the
four-minute journey as a Playwright test.

## Out of scope

- A chat-shaped tester. A builder flow takes one input field and produces one result body (`input_field`, `RUN_RESULT_BODY_KEYS`); a transcript UI would misrepresent it.
- Running a test against a paid backend from CI. Every E2E test that presses a launch button is `@launch`-tagged and runs only against `SYNTHETIC=1` (CLAUDE.md, "seven of 28 are `@launch`").
- Publishing from the panel. Publish stays `PublishDialog.vue` with its six preconditions.

## Design

### D1 — Docked below the canvas, resizable, never modal

The panel is a fourth grid row under `.graph-workspace` — the same
mechanism that put the crew strip *in* the layout rather than over it
(CLAUDE.md §12, "The strip is also in the layout now") — with a drag handle
between 160 px and 60 % of the pane, collapsed by default to a 36 px tab
strip. It never overlays a node: a settling `ResizeObserver` re-fits the
canvas when the panel opens (the same fix as section 14 defect 4,
`BuilderCanvas.vue`). Rationale: R15 and the gauntlet agree ("docked to the
canvas, Flowise-style"), and the gallery/inspector defects 3 and 4 showed
what a pane that steals height without re-fitting does.

### D2 — Five tabs, one pipeline

| Tab | What it does | Cost |
| --- | --- | --- |
| **Run** | picks a saved test input (or types one), posts `mode: test`, renders the run inline: the node states on the builder canvas (`[data-mode='run']`, `builder.css:74-77`, finally written), the dialogue rail (11), the log grouped by node with inputs/outputs/cost (12 D5), the result body | tokens, under the same `$10` ceiling |
| **Node** | picks one node and a saved test input whose `mocks` cover every upstream `out__*`; posts `mode: node_test` (C7); renders only that node's frames | that node's tokens |
| **Dry run** | posts `mode: dry_run` (C7); renders problems, both budget figures, the modelled call count, and the stage plan | **zero** |
| **Code** | `GET /workflows/{id}/compiled` (C7, 09 D8): YAML on the left, Python rendering on the right, copy buttons, credential ids shown as `<credential: label>` | zero |
| **State** | for a finished or paused test run, a step slider over the frame `seq`; `GET /runs/{id}/state?step=` (C7) renders the flow state as a tree with reserved keys grouped (`out__*`, `err__*`, `turns__*`, `__builder__`) and the author's own keys first | zero |

A test run and a real run are the same run (`runs.mode` is the only
difference, C7), so the console's `useValidatorRun` is reused with the
builder canvas as its node surface — one frame pipeline, two tenants, the
way `node-card.css` already serves two cards (R5).

### D3 — Saved test inputs are the author's, per document, and carry mocks

`builder_test_inputs(id, user_id, document_id, name, inputs JSON,
created_at)` (C10, 15). `inputs` is `{<input_field>: str, mocks:
{<node_id>: <JsonScalar | object>}}`. Mocks are the upstream values a node
test seeds through `replay_output` (09 D7, 10 D5). The panel offers *"use
last run's outputs as mocks"*, which copies `out__*` from a finished test
run's state into a new saved input — the cheapest way to get realistic
mocks is a real run, once.

### D4 — Single-node test is a derived plan, not a special runner

`node_test` compiles the derived plan in which every ancestor is
`replay_output` from the saved input's `mocks` and every descendant is
absent (09 D7). A node whose upstream mocks are incomplete is refused with
422 naming the missing `out__<id>` keys before a run row exists. Attachment
nodes cannot be tested alone — they have no output — so the Node tab lists
flow-kind nodes only.

### D5 — Dry run is free and says so

`dry_run` is parse → bounds → budget → compile with no kickoff, no run
row, no rate-limit charge (10 D8). The tab's headline is the modelled call
count and the enforced price, with the sentence *"no tokens were spent"*,
because the gauntlet's fourth rubric-13 line is that nothing above the
ceiling is reachable anywhere, and a dry run that quietly cost something
would be that.

### D6 — The `@launch` contract, and the hole it closes

Every Playwright test that presses **Run**, **Node**, **Re-run from here**
or **Launch** carries `@launch`. `e2e/builder.spec.ts:663` presses Launch
today with **no tag** (`grep -c @launch e2e/builder.spec.ts` → 0;
`AGENTS.md:199-206` calls it a live hole) — this plan tags it. The suite
recipe stays: `--grep-invert @launch` against a deployed origin, the full
suite only against `SYNTHETIC=1` on `:8099` (`playwright.config.ts:16-22,
61-72`).

### D7 — The four-minute journey is a test, timed

`e2e/journey.spec.ts` (`@launch`, synthetic, stubbed sign-in from
`e2e/vite.e2e.config.ts:24-42`): sign in → open the sequential template →
swap the writer's model in the inspector → drag a tool onto the researcher
→ open the panel → **Run** with the template's saved input → watch the
canvas and rail → assert a result body. `page.clock` is not used; wall
time is measured with `performance.now()` around the whole journey and
asserted **< 240 s** with `SYNTHETIC_BRANCH_DELAY_SECONDS=5`. The number is
the gauntlet's "done means"; the delay is what makes the run take long
enough to be watched.

## Interfaces

Consumed only.

- C7: `mode`, `test_input_id`, `node_id`, `dry_run` response, `GET /runs/{id}/state?step=`, `GET /workflows/{id}/compiled`.
- C6: every frame the Run and Node tabs render; `replayed: true` dims the mocked ancestors.
- C10 / 15: `builder_test_inputs` and its routes — `GET /api/builder/workflows/{id}/test-inputs`, `POST` `{name, inputs}` → 201, `DELETE /{test_input_id}` → 204, all owner-scoped, 404 for another user's document.
- C1: `input_field` names the one input key the panel edits.

CONTRACT REQUEST for 00: none — the test-input routes are listed under C10
in 15; this plan assumes that spelling.

## Acceptance criteria

1. `frontend/tests/testPanel.spec.ts`: the panel mounts collapsed, opens to five tabs, is resizable within 160 px–60 %, and opening it triggers a canvas re-fit (the `ResizeObserver` path); no tab renders a modal.
2. `frontend/tests/testPanel.spec.ts`: the Run tab with a `FakeBuilderApi` posts `mode: test` with the chosen `test_input_id` and renders `NODE_START` / `utterance` / `NODE_END` frames from a fixture into the builder canvas's `[data-mode='run']` states — the dormant `builder.css:74-77` rules are exercised by a test for the first time.
3. `frontend/tests/testPanel.spec.ts`: the Node tab lists flow-kind nodes only, refuses to post when mocks are incomplete and names the missing keys, and posts `mode: node_test` otherwise.
4. `frontend/tests/testPanel.spec.ts`: the Dry-run tab posts `mode: dry_run`, renders problems and both budget figures, and shows *"no tokens were spent"*; a `FakeBuilderApi` asserts no run was created.
5. `frontend/tests/testPanel.spec.ts`: the Code tab renders the YAML and Python previews from a fixture generated by the Python renderer (`scripts/emit_builder_fixtures.py`, byte-compared by `tests/builder/test_client_fixtures.py`), and shows `<credential: label>` where the fixture carries a credential id.
6. `frontend/tests/testPanel.spec.ts`: the State tab's slider calls `GET /state?step=` with the frame `seq` and renders reserved keys grouped.
7. `tests/service/test_test_inputs.py`: the three routes, owner scoping, 404-not-403, and the *use last run's outputs as mocks* copy reading `out__*` from `flow_states`.
8. `grep -rn "test(.*@launch" frontend/e2e | wc -l` equals the count of tests that press Run / Node / Re-run / Launch, and `npx playwright test --list --grep-invert @launch` presses none of them (verified by a `FakeBuilderApi`-free run against `:8099` with `RUN_RATE_LIMIT_MAX_RUNS=0`, which would 429 any launch).
9. `e2e/test-panel.spec.ts` (`@launch`, synthetic): Run tab completes a template and shows a result body inline; Node tab runs one node with mocks and shows exactly one node's frames; Dry-run tab shows a price and no run appears in the history list.
10. `e2e/journey.spec.ts` (`@launch`, synthetic, `SYNTHETIC_BRANCH_DELAY_SECONDS=5`): the seven-step journey completes with a visible result in **< 240 s** wall time, measured, with zero console errors tolerated (`e2e/studio.spec.ts`'s existing rule).
11. Rubric 15's half that this plan owns: each of the four templates has a committed saved test input (14) and runs from the Run tab from a cold stubbed sign-in with no configuration.

Rubric dimensions answered: 4 (inspector ergonomics — the test loop is
one panel away), 12 (with 12), 13 (dry run spends nothing), 15 (with 14),
and the gauntlet's "done means" sentence as a timed test.

## References

- `frontend/src/{components/builder/BuilderView.vue:52-57, 430-442, services/builderApi.ts:339-348, assets/styles/builder.css:74-77, components/builder/BuilderCanvas.vue:509, composables/useValidatorRun.ts:822-857}`
- `frontend/{playwright.config.ts:16-22, 33-35, 54-72, e2e/vite.e2e.config.ts:24-42, e2e/builder.spec.ts:663, e2e/studio.spec.ts:203-433}`
- `src/brief_crew/service/{runner.py:65, persistence.py:101-110}`; `AGENTS.md:199-206`
- `docs/flow-builder-spec.md` R4, R5, R15, cut-list 1–2; CLAUDE.md §12 (the strip in the layout), §14 defects 3–4, "Verified Baseline" (the E2E recipe)
- `docs/flowise-notes.md` §5 — `packages/ui/src/views/chatmessage/ChatPopUp.jsx`, `views/agentexecutions/{ExecutionDetails,NodeExecutionDetails}.jsx`
- Gauntlet: "Flow testing", "Done means", rubric 13, 15

## Status

**Planned · 2026-09-02.** No code.

Contract requests for 00: none.

Open decisions for the owner:

- Whether test runs should appear in the run history beside real runs (this plan: yes, labelled `test`, because hiding spend is the failure the cost rules exist to prevent).
- The 240 s budget under a 5 s synthetic delay is the gauntlet's figure, not a measurement of any real journey; the first real-model journey should be timed once and recorded here.
