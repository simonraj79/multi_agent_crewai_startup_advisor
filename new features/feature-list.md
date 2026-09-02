# Validator Studio Feature List

Source: [`PRD.md`](../PRD.md), dated 2026-08-29, for F01–F44.
Since 2026-09-02 this file also tracks work that has **no PRD entry at all** —
see the milestone table's M6 and
[The flow builder](#the-flow-builder--outside-the-prd-feature-set-entirely),
whose contract is [`docs/flow-builder-spec.md`](../docs/flow-builder-spec.md).
Rows outside the PRD are numbered `B01…` so they cannot be mistaken for one.

Validator Studio is additive to the existing Brief Crew. It combines a six-agent CrewAI startup validator with a live Vue 3 graph interface, durable human approval gates, structured evidence, and deterministic scoring.

**And it is no longer the only thing the console does.** A user can now draw a
graph, price it, publish it and run it — the six-agent evaluator is one
*template* on that canvas rather than the only workflow the product has. That is
a change to what the product **is**, and it is the reason this file needed a
fifth reconciliation rather than a count refresh.

## Implementation Status

Last reconciled: **2026-09-02 (fifth pass)**, against `main` = **`b4ef654`**
(the merge of PR #6; the work itself is `6d2743c`), with both suites, the
type-check and the build re-run locally on Windows. Every row below names the
test or the source path it rests on; a row with neither is not evidence.

The fourth pass was **2026-08-30 at `e539811`**. Between then and now the tree
gained authentication, a verdict-frame contract, a throughput-routed validator
and — the reason this pass exists — **a flow builder**. Read the three warnings
before anything else:

1. **Every count in the fourth pass's rows is now wrong**, most of them by more
   than half. Where a row quotes a per-module figure that this pass did not
   re-measure, the figure has been left in place and the row says so; the two
   totals and the per-directory table below **were** regenerated.
2. **Two lines under [Explicit Non-Features](#explicit-non-features) are now
   false.** "No graph editor or user-authored workflow YAML" and "No
   multi-tenant accounts or authentication in the initial release" have both
   been overtaken. Both are struck in place, not deleted. A non-feature that
   shipped is the most misleading kind of stale line in a document like this
   one, because nothing about it looks stale — it reads as a decision, not as a
   measurement, so nobody re-checks it.
3. **Nothing in this pass moved the two things that still gate the product**:
   the paid acceptance run (F42's measurement and F43's citation-closure set)
   and the fan-out measurement. The builder touches neither. The third
   historical gate — human ratification of the rubric — **was** closed, on
   2026-09-01, in [`docs/rubric-ratification.md`](../docs/rubric-ratification.md);
   caveat 6 below is the fourth pass's text and is superseded by it.

Status meanings: **Not started** has no implementation; **In progress** has an active implementation slice; **Partial** has verified behavior but incomplete acceptance criteria; **Complete** has passing executable acceptance evidence; **Blocked** has an external dependency preventing completion.

**Complete means a criterion that a machine checked.** A feature whose acceptance criterion is a *measurement that has never been taken* is **Partial**, however finished the code looks. A feature that ships but has no test is **Partial**, not Complete.

### Measured baseline for this pass

Regenerated on **2026-09-02**, on Windows, at `main` = `b4ef654`. Every figure
below is the output of the command beside it; nothing here was copied from
another document. *The working tree was not clean when these ran — six
documentation files were being edited concurrently, this one among them — but no
`.py`, `.ts` or `.vue` file was modified, so nothing under measurement moved.*

⚠️ **These counts move, and they move fast.** Python has gone
341 → 378 → 415 → 660 → 698 → 713 → **1228**, and the frontend
116 → 126 → 203 → 311 → 324 → **1024**. A browser suite appeared that did not
exist at all, and then quadrupled, 7 → 28. **Re-run before quoting a number; the
command is the contract, not the figure.** Versions and pins are not this file's
to carry — they live in [`../docs/tech-stack.md`](../docs/tech-stack.md).
*(Only the final figure in each ladder was measured here; the earlier ones are
CLAUDE.md's own history, reproduced rather than re-derived.)*

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
# Ran 1228 tests in 162.043s ... OK (skipped=1)

Push-Location frontend; npm test; Pop-Location
# Test Files 54 passed (54) | Tests 1024 passed (1024)   - 12.53s

Push-Location frontend; npx vue-tsc -b --force; Pop-Location
# exit 0

Push-Location frontend; npm run build; Pop-Location
# built in 808ms - GREEN
```

> **One figure disagreed with the brief this pass was given, and the
> measurement wins.** The handoff said the Vitest suite is 1024 tests over
> **49** files. It is 1024 over **54**: `vitest run` reports
> `Test Files 54 passed (54)`, and, from the repo root,
> `find frontend/tests -name '*.spec.ts' | wc -l` independently answers 54. The
> test *count* matched exactly. Recorded rather than quietly corrected, because
> a file-count that drifts while the test-count holds is the signature of specs
> being split, and that is worth someone noticing.
>
> The 162 s Python runtime is also longer than the ~114 s the handoff reports.
> That is an artefact of this pass, not a regression: the Python and Vitest
> suites were run concurrently on one machine.

Per-directory counts, generated by loading each module through
`unittest.TestLoader` rather than by running it, so the breakdown and the total
come from the same walk:

| Directory | Tests | Modules |
|---|---:|---|
| `tests/builder/` | **310** | `test_bounds` 57, `test_compiler` 67, `test_document` 47, `test_from_document` 39, `test_gates` 36, `test_budget` 30, `test_crew_library_arity` 22, `test_client_fixtures` 8, `test_problem_code_declarations` 4 |
| `tests/events/` | 49 | `test_tool_frame_attribution` 19, `test_nested_flow_frames` 11, `test_verdict_frame` 8, `test_spine` 6, `test_run_state_status` 5 |
| `tests/integration/` | 19 | `test_validator_service` 9, `test_ws_gate_replies` 10 |
| `tests/perf/` | 58 | `test_perf_arms` 18, `test_perf_metrics` 40 |
| `tests/service/` | **473** | `test_run_admission` 37, `test_builder_gates` 34, `test_auth_jwt` 28, `test_run_result_and_cost` 26, `test_auth_endpoints` 25, `test_cost_ceiling` 25, `test_gates_mode` 23, `test_restart_recovery` 22, `test_builder_rehydration` 19, `test_graph_etag` 19, `test_observability` 19, `test_synthetic_revise` 19, `test_builder_validate_and_history` 18, `test_builder_runner` 17, `test_gate_fields` 17, `test_graph_crew_binding` 17, `test_cors` 16, `test_unknown_workflow` 15, `test_gate_turns` 13, `test_gate_expiry` 12, `test_gate_resume_race` 11, `test_additive_migration` 6, `test_graph_registry` 6, `test_reserved_key_scope` 6, `test_app` 5, `test_persistence` 5, `test_serve_env` 5, `test_verdict_snapshot` 5, `test_render_blueprint` 3 |
| `tests/tools/` | 43 | `test_indexing` 23, `test_github_feasibility` 8, `test_hn_sentiment` 6, `test_market_research` 4, `test_pinecone_retrieval` 2 |
| `tests/validator/` | **253** | `test_guardrails` 54, `test_gate_turns` 32, `test_rubric_critical_fixes` 31, `test_schemas` 30, `test_flow` 23, `test_crews` 22, `test_report_degradation` 15, `test_query_shape_prompts` 13, `test_rubric_f4_tool_labels` 12, `test_branch_degradation` 9, `test_cache` 8, `test_verdict_event` 4 |
| `tests/test_brief_crew_regression.py` | 23 | — |
| **Total** | **1228** | matches `unittest discover` exactly |
| `frontend/tests/` | **1024** | across **54** spec files |
| `frontend/e2e/` | **28 Playwright tests in 4 files** | not run by `npm test`, **still not run by CI** |

The browser suite is a separate command and a separate contract, and it now has
a precondition it did not have before:

```powershell
# In one shell, the FREE backend. The delay is REQUIRED, see below:
$env:SYNTHETIC="1"; $env:PORT="8099"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS="5"
.\.venv\Scripts\serve.exe

# In another:
Push-Location frontend; npx playwright test; Pop-Location
# 28 tests in 4 files: builder 15, studio 7, visual/run-canvas 3, builder-layout 3
```

⚠️ **Without `SYNTHETIC_BRANCH_DELAY_SECONDS=5` the three
`e2e/visual/run-canvas.spec.ts` specs fail with "No branch stayed in flight".**
The synthetic runner finishes a branch instantly, so there is no running moment
to screenshot. It reads exactly like a CSS regression and is not one. That knob
is read in `service/runner.py`, which is **not** one of the two files the
canonical environment-knob scan covers, so it is absent from that list — see the
report note under [Measurement and verification debt](#measurement-and-verification-debt).

Tagging: **7 of the 28 carry `@launch`** (five in `studio.spec.ts`, two in
`visual/run-canvas.spec.ts`); `--grep-invert @launch` leaves 21. Measured with
`npx playwright test --list` and again with `--list --grep-invert @launch`.

> **For the record, the 2026-08-29 baseline this document was first written
> against**, kept because deleting it would destroy the record of what that pass
> measured: `Ran 415 tests ... OK (skipped=1)`;
> `Test Files 13 passed (13) | Tests 126 passed (126)`; no browser suite at all.

### ⚠️ Read this before trusting any status below

**0. A flow builder shipped, and it is outside this document's numbering
entirely.** `PRD.md` has no F-number for it; its contract is
[`docs/flow-builder-spec.md`](../docs/flow-builder-spec.md). It has its own
section — [The flow builder](#the-flow-builder--outside-the-prd-feature-set-entirely)
— and it changes three things about the rest of this file: the Explicit
Non-Features list now contains a line that is false, `tests/builder/` is 310 of
the 1228 Python tests, and the Playwright suite quadrupled. It changes **no**
F-row's status, because it touches no PRD criterion.

**1. Both discovery gaps from the fourth pass are closed and have stayed
closed.** `tests/events/` and `tests/service/` have `__init__.py`, and so does
`tests/builder/` — added in the same commit as the directory, which is the rule.
The **†** marks used in an earlier revision of this file are gone because
nothing is undiscovered. Standing rule, unchanged: add a test directory's
`__init__.py` in the same commit as the directory, or `unittest discover` walks
past it in silence and reports `OK` over tests it never ran.

**2. The frontend has two test runners, and both have grown by more than 3x.**
Vitest + jsdom (**1024** tests over **54** spec files) and Playwright
(**28** tests in 4 files in `frontend/e2e/`) driving a real browser against a
real FastAPI service over a real WebSocket. F32-F39 are judged on evidence
rather than capped at Partial by default — several still fall short on their own
criteria, and those rows say which clause. *The 203/19 and 7 figures this
paragraph carried until 2026-09-02 were measured on 2026-08-30 and were three
generations stale.*

**3. It is deployed, and that changes fewer rows than it looks like.** As of
2026-08-30 the API, the static site and PostgreSQL 18 are live on Render, and
`/readyz` reports `"backend": "postgresql"`. That is real evidence for the parts
of F44 and F31 about *reaching* a real database. It is **not** evidence for
anything that costs money. Deployment moves F44 from "never applied to a host" to
"applied, and answering health checks"; it moves **nothing** on F42, on F43's
citation-closure clause, or on the rubric review.

**4. ~~Nothing has still been run against paid services.~~ WRONG AS OF
2026-08-30 — corrected 2026-09-02.** A real end-to-end paid run has happened.
CLAUDE.md records it from commits `aa7bdc1` and `add21d1`: it produced a report
**truncated at 4096 characters**, priced at **$0.00 over 128,069 real tokens**,
with **two of three research branches empty** because the Scoper's prose-shaped
queries returned nothing, scoring `NEEDS_WORK 4.2` at **0.17 confidence**. All
three defects have since been fixed and **none has been re-exercised against
live tools.** So the honest form of this caveat is now:

- Every Python test still uses doubles, mocks, `create_app(synthetic=True)` or
  injected crew factories; the browser suite still runs against `SYNTHETIC=1`.
  Nothing below rests on paid evidence.
- One paid run has been made and it found three defects no test could have.
  That is evidence the doubles are insufficient, not evidence the product works.
- **F42 is still unmeasured** and **F43's citation-closure clause still has no
  acceptance set**, so both remain unmeasured rather than merely untested.

A defect the builder work found says the same thing more sharply: a document
naming `crew_id: "synthesis"` passed every structural check, published cleanly,
and raised `TypeError` on the **first paid run** — after the scoper and all
three research branches had billed. The factory call is `Class().crew()`, zero
arguments, and that class has a required `__init__`. No free test could see it,
because no free test constructs the real crew.

**4b. This pass did not make any network call.** CI on PR #6 is reported green
4/4 in the handoff this reconciliation was given; **that was not re-probed
here** — no GitHub API call was made, and the deployed service was not touched.
What *was* read is `.github/workflows/ci.yml`, which declares **two** jobs
(*Python tests (no-cost)* and *Frontend type-check and build*) on
`ubuntu-latest`, neither of which runs Playwright. Treat the 4/4 as reported,
not as verified here.

**5. Defects keep reaching a green suite, and keep being caught by running the
thing.** In the fourth pass it was three: a gate-reply race that permanently
wedged runs, a serializer/UI contract mismatch that meant the UI never showed a
real run finishing, and a paused gate node that rendered as `idle`
(`test_gate_resume_race.py`, `test_run_state_status.py`,
`gateNodeWaiting.spec.ts`, plus the browser suite).

The builder added four more of exactly this shape, and each names its own blind
spot. **All four are reported from the builder work's own handoff and were not
independently reproduced in this pass** — the fixes are in the tree, the
failures are not reproducible from it:

- **Two layout defects invisible to 988 green tests.** On the empty gallery
  neither rail renders, but the shell still declared three columns, so the
  gallery landed in the 236 px palette slot inside a 0 px row — a 236×70 box
  holding 1356 px of content. And the canvas fitted its viewport *before* the
  budget meter and problems dock took their height, so a 16-node template opened
  with its last two nodes under the dock **while reporting itself fitted**
  (scale 0.544, then 0.524, against a settled container wanting 0.466).
  A jsdom mount asserts structure and never asks how wide anything ended up.
  `e2e/builder-layout.spec.ts` asserts both in a real browser.
- **A test that passed only because `unittest discover` sorted two modules in a
  lucky order.** `test_builder_runner.py` leaked a published workflow into five
  process-global registration maps and never unregistered it — and
  `unregister_builder_workflow` cleared only **four** of the five that
  `register` writes.
- **A debug `print` shipped on a production 422 refusal path**, and 1097 green
  tests did not catch it, because nothing asserts on stderr.

The lesson for this file is unchanged and now has five more instances behind it:
a row whose only evidence is a unit test with a double is evidence that the
double is satisfied.

**6. ⚠️ SUPERSEDED 2026-09-01 by
[`docs/rubric-ratification.md`](../docs/rubric-ratification.md), which this pass
did not re-read line by line.** The rubric has since been **ratified** — seven
changes applied, four of them Critical — and the review's *"do not spend money"*
verdict is lifted. Everything below this line is the fourth pass's text, kept
because it is the record of what was true then, and because the paragraph's own
argument (*"a second agent agreeing is still nobody"*) is the thing the
ratification answers. Read the ratification record first; where the two
disagree, it wins. **This pass verified only that the file exists at
`docs/rubric-ratification.md`; it did not audit its contents.**

The fourth pass's text, unedited:

**6. The rubric ladders are audited, adversarially reviewed, and still not
cleared.** `RUBRIC_ANCHORS` in `config.py` binds every verdict at 0.85 token
overlap. PRD §10.2 wrote out only the Demand ladder and labelled it
*"Illustrative"*; M/C/F/X are a derivation, and the PRD's own Demand ladder was
itself defective in three ways (now corrected in PRD §10.2). The ladders pass
tests. No human has read them.

An independent adversarial pass now exists — [`docs/rubric-review.md`](../docs/rubric-review.md)
— and its answer is **"do not spend money on a live acceptance run against this
rubric as it stands"**, on the grounds that three of the five ladders will
produce confidently wrong verdicts on ordinary ideas, each triggerable by an
evidence state the schemas represent and the guardrails accept in silence. Its
two **Critical** findings are still true at head: `FLOOR_ALREADY_FREE` counts
only GitHub repositories, so a free *product* covering the whole core job cannot
fire the kill the PRD says justifies the system; and D=0's `zero_ok = usable >= 1`
issues a final `REJECT / FLOOR_NO_DEMAND` on a single off-hand comment with
`provisional=False`, in a configuration where the confidence override is
structurally unable to intervene. **Nothing in this pass touched the rubric** —
`git show e539811 -- src/brief_crew/config.py` contains no anchor change, and
`validator_guardrails.py` and `schemas/validator.py` were not in the commit at
all. Being deployed and being green do not move this row.

**7. CI has been green since `e539811`, and the defect it exposed was an
environment assumption, not a test.** *The `Ran 415 tests in 15.823s` below is
the run at `e539811` and has been left as the record of it; the suite is
**1228** now, and no CI run at `b4ef654` was inspected in this pass.* As of
`e539811` both jobs pass on `ubuntu-latest`; the three commits before it all
failed. The cause: `brief_crew/__init__.py` calls `load_dotenv(override=True)` at
import, and ~40 tests *construct* real `LLM` and Firecrawl objects to assert
their wiring, both of which demand a key in `__init__`. The suite therefore
passed on any machine with a `.env` and collapsed on a clean checkout — 4
failures and 36 errors at construction time. `tests/__init__.py` now `setdefault`s
two obviously-fake placeholders before `brief_crew` is imported. The consequence
worth recording here: **the suite's no-cost claim is now verified by a machine
that has no keys at all**, rather than asserted on machines that happened to
have them.

### Milestone status

| Milestone | Features | Status | Verified evidence, and what is missing |
|---|---|---|---|
| M-1 Prerequisites | F25 plus event and persistence prerequisites | **Partial** | `BriefFlow.check_cache` returns `Literal["cache_hit", "cache_miss"]`; both router edges appear in the derived graph — `tests/test_brief_crew_regression.py::GraphIntrospectionTests` (2 tests), `tests/service/test_graph_registry.py::test_brief_flow_graph_has_both_router_branches`, `tests/integration/test_validator_service.py::test_both_graphs_are_exposed_with_derived_routes`. `PostgresFlowPersistence` round-trips — in tests, on **SQLite only**; it has since created its schema against real PG 18 on the deployed service, but no automated test runs there. |
| M0 Event spine | F19-F24 | **Partial** | All six `tests/events/test_spine.py` tests are now discovered, and `tests/service/test_observability.py` (19 tests) adds METRICS emission and coalescing, the unattributed count in run status and across recovery, writer cadence, handler latency and run eviction. The one criterion still unmet is **F22's "one loading bubble per active node"** — chips are per call in a flat chronological list. |
| M1 Service | F25-F31 | **Partial** | All 11 endpoints exist and are covered across `tests/integration/` (19) and `tests/service/` (**473 as of 2026-09-02**, of which 88 are builder modules that belong to M6 below; the *96* this row used to quote was measured 2026-08-30 and this pass did not re-partition the rest by milestone): both graphs and ETag, two gate round trips over HTTP *and* WebSocket, 409 on duplicates, gapless frames, replay + ping/pong, NDJSON and ZIP, cancellation, gate expiry, run eviction, frame-writer cadence, durable recovery in a fresh app, cross-origin policy (`test_cors.py`, 16) and the gate-reply settling race (`test_gate_resume_race.py`, 11). The graph and health endpoints are additionally served in production against real PostgreSQL. Missing: any **PostgreSQL exercise under concurrency** (F31) — the deployed service proves the dialect works, not that two writers contend correctly — and F26's queueing under `RUN_CONCURRENCY > 1` is still asserted on the executor's configuration rather than on an observed queued-then-started run. |
| M2 Studio | F32-F39 | **Partial** | A real Vue 3 + Vue Flow application. Suite-wide the frontend is **1024 Vitest tests over 54 files** and **28 Playwright tests in 4 files** (measured 2026-09-02); the *203 / 19 / 7* this row quoted was 2026-08-30, and **this pass did not split the new totals between M2 and M6**, so do not read either number as this milestone's own. Still true and still M2's: a spec asserts `MOCK_GRAPH` matches the live descriptor node-for-node and edge-for-edge, and Playwright drives a real browser through both durable gates. Two defects the unit tests could not see were found by running it and are now pinned: the UI never left its pre-run state on a real run (`tests/events/test_run_state_status.py`, 5, plus `frontend/tests/realFrameShape.spec.ts`, 6, both against one committed serializer fixture) and a paused gate node rendered as `idle` (`frontend/tests/gateNodeWaiting.spec.ts`, 4). Unmet criteria remain in **F34** (no sprites at all), **F35** (no sprite along the path, no path-length duration, no shared `<defs>`, no self-loop), **F36** (4 entry variants of the 7 named, no `ResizeObserver`), **F37** (evidence gaps still absent from the verdict card, and the node has no `expired` state), **F38** (no workflow selection) and **F39** (guardrail exhaustion is unrepresented). |
| M3 Validator | F01-F18, F40, F42 | **Partial** | **296** discovered tests across `tests/validator/` (**253**) and `tests/tools/` (43), measured 2026-09-02 — the row previously said 171 / 128 / 43. The 125 added to `tests/validator/` account exactly: **116** in seven modules that did not exist then (`test_gate_turns` 32, `test_rubric_critical_fixes` 31, `test_report_degradation` 15, `test_query_shape_prompts` 13, `test_rubric_f4_tool_labels` 12, `test_branch_degradation` 9, `test_verdict_event` 4) and **9** of growth in the four that did (`test_crews` 19→22, `test_guardrails` 51→54, `test_flow` 21→23, `test_schemas` 29→30). None of it is new PRD coverage. They cover the schemas, the deterministic verdict, all five rubric ladders and their evidence support, the guardrails, all three tools, the branch cache and the three-way fan-out. **F42 has still never been measured** — the harness exists and is tested, the run has not happened. |
| M4 Gates | F03, F12, F27, F37 | **Partial** | Both native `@human_feedback` gates pause, persist and resume across a fresh app instance; server-side expiry runs an `expired` → `alerted` watch ladder that never auto-answers (`tests/service/test_gate_expiry.py`, 12 tests); gate replies now land over **both** HTTP and the WebSocket through one compare-and-set (`tests/integration/test_ws_gate_replies.py`, 10 tests). The WS slice that made this "In progress" is finished, and the verdict gate now sends the whole `Verdict` as read-only `derived` fields, so the rubric *is* on the card (`tests/service/test_gate_fields.py`, 17 tests; `frontend/tests/gateDerived.spec.ts`, 13 tests). What remains is UI content, not transport: the branch **evidence gaps** are still not carried to the gate, because `Verdict` has no gaps field. |
| M5 Hardening | F23-F24, F29-F31, F41-F44 | **Partial** | Usage accounting, backpressure, log export, run eviction and durable persistence are implemented and tested. **The service is deployed** — API, static site and PostgreSQL 18 live on Render, `/readyz` reporting `"backend": "postgresql"`, CORS enforced (`tests/service/test_cors.py`, 16) and verified against the deployed origin. Held at Partial because the criteria that make M5 *hardening* are still open: F42 unmeasured, F43's citation-closure acceptance set does not exist, no run has ever *finished* against the deployed service (two were launched on 2026-08-30 and both stopped at the scope gate), and no graceful shutdown or persistence flush has been observed on the host. `render.yaml` remains **unapplied** — the two services were created through the Render API instead — and `Dockerfile` has never been built. |
| **M6 Flow builder** | *(none — outside the PRD)* | **Partial** | Not a PRD milestone and not in the Delivery Order below; added here 2026-09-02 so the largest thing in the tree is not invisible to the only document that tracks status. A canvas document parses, is structurally bounded, is priced, compiles to a real `crewai.flow/v1` declaration, publishes as a workflow and **runs** — gates open on the author's own canvas node id, resume produces output, cancel reaches CANCELLED, and a published graph survives the restart `autoDeploy: yes` guarantees on every push to `main`. Evidence: `tests/builder/` **310**, plus **88** in `tests/service/` (`test_builder_gates` 34, `test_builder_rehydration` 19, `test_builder_validate_and_history` 18, `test_builder_runner` 17), plus `tests/service/test_cost_ceiling.py` 25 and `test_graph_crew_binding.py` 17; on the client, 16 builder spec files (`ls frontend/tests/builder*.spec.ts | wc -l`) and `e2e/builder.spec.ts` (15) + `e2e/builder-layout.spec.ts` (3). **Partial, not Complete**, and for one reason that is not a missing test: **no published builder graph has ever been run against paid models.** Every run above is `SYNTHETIC=1` — the real compiled definition through the real engine, with only the model call replaced. The one time a builder graph did meet real money it found a `TypeError` after four billed nodes (caveat 4). |

### Feature Evidence Ledger

Every test path below was run in this pass. Counts are from
`python -m unittest <module>`.

#### Core validation workflow

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F01 Startup Idea Submission | **Partial** | `run_id` is a fresh UUID under a caller-supplied `session_id` (`service/registry.py::create_run`); queueing is a `ThreadPoolExecutor(max_workers=RUN_CONCURRENCY)`; all seven states exist in `service/models.RunStatus`. Tests: `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`, `tests/service/test_graph_registry.py::test_default_executor_uses_configured_run_concurrency`. Missing: the CLI (`validator_flow.py::_build_parser`) accepts `--idea`, `--resume`, `--feedback`, `--namespace`, `--feasibility-cache` and `--no-gates` but **no `--session-id`**; the Studio's primary action is only ever `Launch`/`Relaunch`, so the criterion's "Send" affordance does not exist. |
| F02 Structured Idea Scoping | **Partial** | Scoper on `ESCALATION_MODEL` with `tools=[]`, asserted by `tests/validator/test_crews.py::test_single_agent_crews_use_expected_models_and_tool_surfaces`. `ScopedIdea` carries every required field including 3-5 `assumptions` and `as_of`. Query lists are joined with `"\n".join(...)` before interpolation. Missing, unchanged: **query quality is not validated at all** — `validator_guardrails.scope_problems` checks the assumption count and that at least one scoping gap is named, and nothing else; "category-based queries rather than generic keyword appending" exists only as prompt prose. |
| F03 Scope Confirmation Gate | **Complete** | Native `@human_feedback` pause, editable fields, deterministic `@router` with zero LLM calls, durable pending feedback, resume across a fresh app instance — `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`, `::test_pending_gate_recovers_and_resumes_in_a_new_app`. Expiry: a background sweeper advances an unanswered gate along an `expired` → `alerted` ladder that leaves `answered_at` NULL, so the run stays `waiting`, is never auto-answered, and a late reply still resumes it — `tests/service/test_gate_expiry.py` (12 tests) plus `tests/integration/test_ws_gate_replies.py::WebSocketLateGateReplyTests`. |
| F04 Parallel Research Fan-Out | **Partial** | Three sibling `@listen("scope_approved")` methods with an `and_()` join, one single-agent Crew each, all three distinct graph nodes. `tests/validator/test_flow.py::test_no_gate_flow_fans_out_transitions_and_persists` asserts a measured `ConcurrencyTracker.maximum == 3`; `::test_flow_definition_has_three_siblings_and_one_join` asserts the topology. **The sequential fallback now exists** — `VALIDATOR_SEQUENTIAL_BRANCHES` plus a per-branch turnstile with `VALIDATOR_BRANCH_TURN_TIMEOUT_SECONDS`, so R-3's withdrawal is a deploy-time flip. Held at Partial because the criterion the fallback exists to serve (F42) has never been measured, so nobody knows whether it is needed. |
| F05 Market Landscape Research | **Partial** | Cheap-tier analyst + Firecrawl search-with-scrape; both `Document.url` and `metadata.source_url` shapes handled; plan/rate-limit detection is substring- and status-code-based with no hard-coded quota. `MarketFindings.paying_segments` now exists with its own validator, and `Evidence.dated_is_retrieval_time` is set on every row that fell back to the retrieval timestamp. Tests: `tests/tools/test_market_research.py` (4). Missing: `MarketFindings` still carries **no `retrieved_at`** (the retrieval time lives on the tool envelope only), and the 402 / "plan limit" branch is still untested. |
| F06 Community Sentiment Research | **Partial** | HN Algolia story search then comment-tree retrieval; citations always derived from `objectID`, so a null `story_url` cannot break them; 429 detected without reading rate-limit headers. **`Thread.points` and `num_comments` are now populated** — `tools/hn_sentiment.py::_story_metric` reads them from the Algolia story record and the envelope notes stories that reported none. Tests: `tests/tools/test_hn_sentiment.py` (6). Missing: there is still **no back-off** — on 429 the tool raises, discards partials and returns `rate_limited`. |
| F07 Technical Feasibility Research | **Partial** | Module-level shared token buckets at exactly 8/24 req-min, `User-Agent` on every request, honest `rate_limited`, relevance/license/activity capture. **`Repo.archived` is now populated** — `tools/github_feasibility.py::_archived` reads it from the search item or the detail payload, stays tri-state, and the envelope notes how many results reported none. Tests: `tests/tools/test_github_feasibility.py` (8). Missing: "implementation signals" is still only a token-overlap heuristic, and the raw SPDX identifier is reduced to a boolean rather than carried. |
| F08 Structured Tool Results and Evidence Closure | **Partial** | All three tools return the seven-key envelope; URL-less results are dropped with a note; `URL_CLOSURE` rejects findings URLs outside the captured set; failed/empty/rate-limited status forces empty sources plus an explicit gap, and for market also forces `paying_segments` empty. Tests: `tests/validator/test_guardrails.py` findings cases. Missing, unchanged: the recording tool subclasses and `_capture_urls` in `validator_crew.py` have **no direct test**; at the report stage the allowed set is re-derived from findings rather than from the recorded raw tool URLs. |
| F09 Evidence Synthesis | **Partial** | Synthesist on escalation tier with `tools=[]`, consuming all three branches only after `and_()`; five anchored `DimensionScore`s; evidence counts recomputed and enforced by exact equality. **Reasoning effort is now explicit** — `VALIDATOR_SYNTHESIST_REASONING_EFFORT = "high"`, delivered through `openrouter_reasoning_params()` into `LLM(additional_params=...)` because `reasoning_effort=` is silently dropped for OpenRouter in CrewAI 1.15.18. Remaining divergence, deliberate: the model's kill-criteria candidates are discarded and replaced by the computed floor list, and there is no separate draft verdict. |
| F10 Deterministic Rubric and Verdict | **Complete** | `Verdict.compute_mechanical_result` computes composite, verdict, confidence, band and provisional in a `@model_validator(mode="after")`. `tests/validator/test_schemas.py` (29 tests) submits a fixture with deliberately wrong model arithmetic and asserts every field is overwritten; covers the 7.0 and 4.0 thresholds at the boundary, all four floors, floor ordering, and confidence-override-before-floors. Reproducibility is a property of a pure validator on a frozen model rather than a dedicated two-run test. |
| F11 Mechanical Confidence Scoring | **Complete** | Weighted coverage, staleness multiplier, the 0.60 branch penalty and all three band boundaries are computed and tested; provisional labelling is enforced in **both** title and summary; LOW-confidence wording is rejected. The previous gap is closed: `validator_guardrails.compute_confidence_inputs` now **recomputes** the three coverage ratios and the median market-source age from the branch findings and rejects the model's assertions against them, and `_market_source_age_months` returns `None` for a row dated by the retrieval clock so an undated page cannot read as fresh. `VALIDATOR_COVERAGE_TARGET_SOURCES` and `VALIDATOR_DAYS_PER_MONTH` carry the constants. |
| F12 Verdict Review Gate | **Partial** | Second native gate pauses after synthesis, routes deterministically, and preserves a structured operator override. The rubric gap is closed: the gate payload now splits into `fields` (editable) and `derived` (read-only), and for `review_verdict` **every** `Verdict` key is derived — the five `DimensionScore` objects with their `anchor_matched` and `evidence_urls`, `evidence_counts`, the three coverages, `kill_criteria`, `cheapest_next_test`, and the seven recomputed arithmetic fields. `fields` is *pruned* rather than annotated, so a stale client cannot keep offering an edit the server would discard. Tests: `tests/service/test_gate_fields.py` (17), `frontend/tests/gateDerived.spec.ts` (13), `tests/integration/test_validator_service.py::test_two_gate_round_trips_duplicate_replay_and_logs`. Missing: the criterion also asks for **evidence gaps**, and `Verdict` carries none — the branch `gaps` lists stop at synthesis and never reach the gate. |
| F13 Validation Report Generation | **Partial** | Reporter on escalation tier; `output_pydantic=ValidationReport` with `output_file` absent, asserted by `tests/validator/test_crews.py::test_tasks_have_structured_outputs_and_report_has_no_output_file`; the Markdown body is written by the Flow `persist` step, asserted in `test_flow.py`. **Risks are now requested** in `reporting_task`, with an instruction to cite each risk that rests on a source and not to restate the kill criteria. Missing: `report_mechanics_problems` still checks only URL closure both ways, the `# ` title line, the provisional flag/title/summary, `thin_dimensions` and LOW-confidence wording — **not** the score table, kill criteria, cheapest next test, risks section or Sources heading. Fail-on-exhausted-retries still relies on CrewAI's own raise and nothing here tests it. |

#### Schemas and guardrails

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F14 Pydantic Validation Models | **Complete** | All five leaf models and all six stage models present. URLs validated with an actionable message and stored as `str` — no `HttpUrl` anywhere; `source_urls` mirror validators on all three findings models. `tests/validator/test_schemas.py` (29 tests) covers actionable messages, exact source mirroring, duplicate rejection, the computed `evidence_thin` flag and strict non-coercion of score strings. |
| F15 Zero-Cost Mechanical Guardrails | **Partial** | 51 tests in `tests/validator/test_guardrails.py`. Status honesty, URL closure, count consistency, required gaps, evidence-count recomputation, report structure, confidence language and provisional labels all implemented and tested; `parse_raw_model` returns successful raw text **byte-identical**, asserted by exact equality. The previous headline gap is closed: **`RUBRIC_ANCHORS` now carries all five ladders**, so M/C/F/X are bound at 0.85 overlap rather than accepting any prose, and `score_support_problems` / `rubric_support` additionally bound each score against the counted evidence. Held at Partial for one unchanged clause: **query quality is still not validated at all**. |
| F16 Citation Judgement Guardrail | **Complete** | Exactly one string guardrail, on the reporting task only, ordered after the mechanical callable, with the prompt text pinned in YAML and hard-checked against a constant so it cannot drift. This is now executable rather than read: `tests/validator/test_crews.py::test_guardrail_sets_are_exactly_as_specified` asserts the count, type and position of every guardrail on every task and that the single-guardrail `guardrail=` field stays unused, and `::test_exactly_one_llm_guardrail_and_it_is_last_on_the_report` asserts there is exactly one string guardrail and where it sits. |

#### Cache and retrieval

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F17 Branch-Level Warm Cache | **Complete** | Lookup happens inside `@listen("scope_approved")` steps, so never before confirmation. Market always, sentiment **never**, feasibility opt-in; branch-specific score and age thresholds; cached evidence labelled with source and retrieval dates and explicitly marked supplemental. Tests: `tests/validator/test_cache.py` (8 tests) plus `tests/validator/test_flow.py::test_market_cache_supplements_but_never_skips_live_research` (asserts the order lookup → live → index) and `::test_sentiment_branch_never_looks_up_cache`. |
| F18 Safe Evidence Indexing | **Complete** | One document per source URL with `branch`, `category`, `idea_hash`, publisher and timestamps; branch+category metadata filters reach `index.query(filter=...)`; per-user namespace is an opaque SHA-256 digest that provably does not leak the identity; `ScopedIdea`/`Verdict`/`ValidationReport` are rejected **before any embedding spend**. Tests: `tests/validator/test_cache.py`, `tests/tools/test_indexing.py` (23), `tests/tools/test_pinecone_retrieval.py` (2). |

#### Live event and observability spine

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F19 Ordered CrewAI Event Capture | **Complete** | ContextVar-scoped stream sink (`events/context.py`) with an opt-in `async def` listener fallback and **no plain sync handler anywhere**; run context is re-established around resume as well as initial kickoff; an ordinary CLI run installs no sink so its events are ignored. Tests: `tests/events/test_spine.py::test_capture_is_scoped_ordered_and_immutable`, `::test_concurrent_contexts_do_not_leak_frames` (both now discovered), and `tests/service/test_observability.py::test_capture_never_blocks_on_or_performs_database_writes` proves the no-I/O clause rather than asserting it. |
| F20 Versioned Frame Protocol | **Complete** | `{type:"frame", data:{...}}` with `v`, gapless `seq`, run id, timestamp, kind, event type, level, node id, message, bounded details and duration; field-by-field mapping with **no `to_json()` and no whole-object traversal**; a structured `edge_taken` frame emitted from the router's return value. The last gap is closed: **`FrameKind.METRICS` is emitted** — `registry.py` snapshots run and per-node usage as a `METRICS_UPDATED` frame capped at `MAX_METRICS_NODES`. Tests: `test_spine.py::test_router_finish_emits_node_end_then_edge`, `::test_serializer_clips_fields_without_serializing_live_objects`, and `test_observability.py::MetricsFrameTests` (5 tests: terminal snapshot, coalescing against ring flooding, no frame when no model was called, the interval snapshot, and a snapshot before a gate pause). **A serializer/client contract mismatch is fixed and pinned:** `serializer.py` emitted `RUN_STATE` for flow start and finish carrying only `{inputs}` / `{result}` while the client read `details.status` alone, so the UI never left its pre-run state on a real run — invisible to 116 green tests because every double happened to send a status and every frontend spec asserted against `event_type` values the backend never emits. Both drafts now carry `status`, both synthetic runners match the real shape key-for-key, and backend and client are pinned to **one committed fixture generated by the real serializer** so they cannot drift apart again: `tests/events/test_run_state_status.py` (5) and `frontend/tests/realFrameShape.spec.ts` (6) over `frontend/tests/fixtures/backendRunStateFrames.json`. |
| F21 Stable Node Attribution | **Complete** | Declared node ids in the graph descriptor; the exact task-name → agent-role-prefix → current Flow method → quarantine chain; each fan-out branch is its own Flow method; the `unattributed` node is present and visible in both descriptors. The last gap is closed: **unattributed frames are counted and exposed in run status** — `test_observability.py::UnattributedFrameTests` (3 tests) covers the buffer counting only quarantined frames, run status reporting the count, and the count surviving recovery from storage. The Studio renders the node and its count (`frontend/tests/quarantineNode.spec.ts`, 8 tests). |
| F22 Token Streaming and Call Timing | **Partial** | `LLMStreamChunkEvent` becomes a non-blocking `llm`/chunk frame; before/after pairs drive live timer chips in the rail with a 100 ms ticker, frozen on completion. Missing, unchanged and the only F19-F24 criterion still unmet: **no per-node loading bubble** — chips are per call inside a flat chronological list, so during the three-way fan-out there is no per-node "this node is thinking" affordance. |
| F23 Per-Run and Per-Node Usage Accounting | **Complete** | Accumulation keyed on `(node_id, model)` with prompt/completion tokens, calls, elapsed ms and cost priced through `compute_cost_usd()`; a `Flow.usage_metrics` discrepancy is **logged rather than silently resolved**. Tests: `tests/service/test_graph_registry.py::test_llm_usage_is_priced_persisted_and_exposed_by_node_and_model`, `::test_flow_usage_mismatch_is_logged_without_failing_the_run`. The UI half is now covered too — `frontend/tests/frameHandling.spec.ts::accumulates run and per-node token usage`. |
| F24 Bounded Backpressure | **Complete** | 2,000-frame ring counting evictions as both drop and gap; 512-frame subscriber queues counting drops; a separate `_PersistenceWriter` thread doing every DB write; counters exposed in run status. Tests: `tests/service/test_graph_registry.py::test_status_and_replay_are_bounded`, `tests/events/test_spine.py::test_ring_reports_eviction_as_drop_and_gap` (now discovered), and `test_observability.py::FrameWriterCadenceTests` (4 tests) for the writer's size/interval/flush/stop behaviour. |

#### Backend service

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F25 Workflow and Graph APIs | **Complete** | Both endpoints live; topology derived from `build_flow_structure()`; the overlay is validated key-for-key against the derived node set and **startup raises if any router lacks statically inferable events**; ETag set from a content hash. Tests: `tests/integration/test_validator_service.py::test_both_graphs_are_exposed_with_derived_routes` asserts both cache routes, both gate kinds, the quarantine node, fixed layout metadata and the three-way `scope_approved` fan-out; `tests/service/test_app.py::test_graph_run_status_and_frames_contract` adds the ETag header. |
| F26 Run Lifecycle APIs | **Partial** | `POST /api/sessions/{sid}/runs` returns 202 with run id, status and graph version; `GET /api/runs/{rid}` returns status, pending gate, frame counters, error and usage; `GET .../frames` supports `after`, `limit` capped at `MAX_REPLAY_LIMIT=500` and comma-separated kind filtering; `run_id` is distinct from `session_id`. Run records are now evicted after `VALIDATOR_RUN_RETENTION_SECONDS` and rehydrated from storage on the next read (`test_observability.py::RunEvictionTests`, 5 tests). **The run-creation endpoint is now bounded** — see *Public-API admission control* below; the refusals are part of this endpoint's documented contract (`413`, `422`, `429`) and are declared in its `responses=` block. Held at Partial for one unchanged reason: queueing under `RUN_CONCURRENCY > 1` is asserted on the executor's **configuration**, never on an observed queued-then-started run. |
| F27 Human Gate APIs | **Complete** | HTTP replies, structured approve/revise, HTTP 409 on a duplicate through a real SQL compare-and-set (`UPDATE ... WHERE answered_at IS NULL` + `rowcount == 1`), and pending-gate recovery through run status. **Gate replies over WebSocket landed and are tested** — `service/app.py::handle_gate_reply` shares the same compare-and-set, bounded by `WS_MAX_MESSAGE_BYTES` / `WS_MAX_GATE_FIELDS` / `WS_MAX_GATE_FIELD_CHARS`. Tests: `tests/integration/test_ws_gate_replies.py` (10 tests — socket reply resumes the run, WS and HTTP produce identical frames, duplicate refused while the socket stays usable, malformed messages refused without killing socket or run, ping/replay/`after` survive a reply, the stream keeps flowing during a reply, and a late reply after expiry still resumes), plus `tests/service/test_app.py::test_websocket_refuses_control_messages_on_a_gateless_run` and three `frontend/tests/studioApi.spec.ts` cases. **A race that permanently wedged runs is fixed and pinned** — `_mark_pending` published the gate from inside `_execute`, so a reply landing before the worker's own future settled was accepted durably and then refused by `_submit`, leaving the run `RUNNING` forever with no gate to answer and 409 on every retry (seen on 3 of ~16 live runs). `_submit` now waits out a settling future **outside** the registry lock, `RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS` bounds the wait, a still-refused resume rolls back through `persistence.reopen_gate` and re-emits `GATE_OPEN`, and HTTP answers **503** rather than 500 because resending works. `tests/service/test_gate_resume_race.py` (11 tests). |
| F28 Cooperative Cancellation | **Complete** | `POST .../cancel` marks the run cancelling; a per-run scoped `PRE_STEP` hook raises `HookAborted` at the next boundary; the response returns an explicit `effect` and `eta_hint`, and the UI holds "Stopping…" until a server `run_state` frame confirms. Test: `tests/integration/test_validator_service.py::CancellationIntegrationTests::test_cancel_stops_at_next_runner_boundary`. |
| F29 Log Export | **Complete** | NDJSON and ZIP both served; the ZIP contains `frames.ndjson`, `run.json` and `node-metrics.json`; Download Logs is wired in the Studio controls with a spinner and error state. Tests: the integration test asserts NDJSON ordering and completeness; `tests/service/test_app.py::test_health_readiness_and_log_exports` covers ZIP; `frontend/tests/downloadLogs.spec.ts` (10 tests) covers the browser half — object-URL minting and revocation, the ZIP filename, percent-encoded run ids, anchor cleanup, and both failure paths. |
| F30 Reconnecting WebSocket | **Complete** | `/ws?session_id=&run_id=&after=` with ping/pong, sequence replay, an explicit `replay_gap` when the cursor is behind the ring, `replay_truncated` when more remains, client-side dedup and exponential backoff; a slow subscriber drops from its own bounded queue rather than blocking the run. The last gap is closed: **run records are pruned** after `VALIDATOR_RUN_RETENTION_SECONDS`, with a connected subscriber pinning a terminal run and a `waiting` run never evicted (`test_observability.py::RunEvictionTests`). Client side: `frontend/tests/studioApi.spec.ts` (cursor, reconnect-and-resume, malformed message, idle ping, unsubscribe). |
| F31 Durable Run Persistence | **Partial** | Runs, node metrics, ordered frames, gates, session/workflow/flow ids and graph versions all persisted; `PostgresFlowPersistence` implements CrewAI `FlowPersistence` for state and pending feedback; `RUN_CONCURRENCY=1` default with queueing; resumability proven across a **new app instance**, with SQLite round trips, frame ordering and idempotency in `tests/service/test_persistence.py` (5 tests). Frame batching is no longer size-only: `VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS = 0.25` bounds the wait for a partial batch, tested in `test_observability.py::FrameWriterCadenceTests`. **PostgreSQL is no longer hypothetical**: the deployed API reports `"storage": {"backend": "postgresql"}` on `/readyz`, so `init_db()` created every table against a real PG 18 instance over Render's internal network. Still Partial, and the clause is now narrower than it was: everything *automated* runs on **SQLite**, and the compare-and-set that `pending_feedback` and the gate reply depend on (`UPDATE ... WHERE ...` + `rowcount`) is exactly what SQLite's single-writer model cannot stress. Two processes replying to one gate has never been tested anywhere. |

#### Studio UI

The frontend has executable tests — 203 Vitest specs across 19 files, plus 7
Playwright specs in a real browser — so these rows are judged on their own
criteria rather than capped by a missing runner.

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F32 Three-Pane Validator Studio | **Partial** | Vue 3 + Vite + Vue Flow; a real three-column grid filling `100dvh`; **both** side rails collapsible; tablet breakpoints at 1180 px and 860 px plus `prefers-reduced-motion`. Unchanged divergence from the criterion: the segmented control is **Graph / Activity, not Chat / Graph**, and it is not a view mode — above 860 px "Activity" only un-collapses the chat rail. `min-width: 720px` on `html, body`. |
| F33 Fixed Live Agent Graph | **Partial** | Fourteen fixed nodes at literal positions, non-draggable/non-selectable/non-connectable, matching the live descriptor exactly — `frontend/tests/mockGraph.spec.ts` (18 tests) asserts the node list and edge list against `build_graph_descriptor(ValidatorFlow, ...)` in order, plus the fan-out, the AND join, both revise loops and the router classification. The **Unattributed node is now rendered and counted** (`quarantineNode.spec.ts`, 8 tests). The criterion's five distinct states are finally all reachable: **`waiting` was dead code** — `applyNodeState` tested `event_type.includes('WAITING')` and no `UIEventType` member contains that substring, while a gate arrives as `GATE_OPEN` / `HUMAN_INTERACTION` and routed to `applyGate`, which set the *run* status and never touched the node. A paused gate therefore drew identically to a node that had never run: while the operator was being asked to confirm the scope, `confirm_scope` looked exactly like `revise_scope`. Fixed, with `gate_open` now setting the node the way `gate_closed` always did (`frontend/tests/gateNodeWaiting.spec.ts`, 4 tests, plus the browser suite that found it). Missing: **no lock control** — `:show-interactive="false"` explicitly disables it; **no start-state node**; and node height is still not stable, because the meta and usage blocks are `v-if` so nodes grow when usage arrives. |
| F34 Node and Sprite Identity | **Partial — deliberate divergence, still undecided** | **The PRD's 144 downscaled 64×80 character PNGs were never imported, and this is a deliberate substitution rather than an oversight.** Re-verified in this pass: nothing under `frontend/src` mentions a sprite. What ships instead: kind-based Lucide glyphs, a static per-node eyebrow string, and two-letter initials on chat avatars. Consequences to accept or reject explicitly: **no per-agent palette**, **no hash-based assignment**, **no two-frame walk cycle**. Decide whether the vector identity is the accepted answer and amend the criterion, or whether the sprite work is still owed. |
| F35 Edge and Handoff Visualization | **Partial** | Bezier paths, marching-dash animation on active edges, condition labels through `EdgeLabelRenderer`, driven by structured `edge_taken` frame details. The fan-out defect is fixed: `activeEdgeIds` is a `Set`, so **all three branches animate at once** — `frontend/tests/edgeAnimation.spec.ts` (8 tests) covers simultaneous animation, independent lifetimes, stopping on branch completion and on error, re-taken edges, clearing on a terminal state, no carry-over across relaunch and no timer leak on unmount. Missing: **no self-loop case**, **no sprite animated along the path**, **no duration derived from path length** (both timings hard-coded), **no shared SVG `<defs>`** — the glow is a per-edge CSS `drop-shadow`. |
| F36 Live Chat Rail | **Partial** | Timestamped entries in a `role="log" aria-live="polite"` container, auto-scroll, an accessible Show More/Show Less with `aria-expanded`, and timed tool/model chips that tick live and freeze on completion. Missing, unchanged: **four variants, not seven** — `agent`, `system`, `warning`, `error`, so a `gate_open` renders as a generic warning bubble with no `tool`, `model` or `human-interaction` variant; **no `ResizeObserver`** — collapsing is a raw `message.length > 180` heuristic; per-node attribution is an actor name in a flat interleaved list. |
| F37 Gate Interaction Cards | **Partial** | Editable structured fields seeded from the gate payload; a live `expires_at` countdown; the card survives refresh via `localStorage` + `GET /api/runs/{id}` and survives a socket drop (`frontend/tests/runRecovery.spec.ts`, 7 tests). Two things were **corrected** during this pass and are tested. Expiry is *informational*, never a lockout — every option stays enabled, a late reply still submits with its edited fields, and the wording reads as a notice (`frontend/tests/gateCard.spec.ts`, 8 tests), matching the server behaviour under F03. And the verdict card now renders the whole rubric as a read-only `derived` section rather than as text inputs the server would discard (`frontend/tests/gateDerived.spec.ts`, 13 tests). Missing: **evidence gaps are still not on the card** (nothing carries them to the gate), and **expiry is card-only — `NodeRunState` has no `expired` member**, so the node stays visually `waiting`. |
| F38 Run Controls | **Partial** | Read-only status badge, Launch/Relaunch/Cancel/Download Logs with a format picker, Lucide icons throughout; Relaunch immediately starts a new run with the current idea; cancellation waits for a server `run_state` frame before showing `cancelled`. Missing, unchanged: **no workflow selection** — `StatusPanel.vue` prints the literal string "Idea Validator" in a read-only well and `workflowId` cannot be changed from the UI; the criterion's "Send" label does not exist; and the three primary actions carry no `title` tooltips (only the log-format buttons and the run id do). |
| F39 Error and Recovery UX | **Partial** | Frame drops counted and shown in red; four connection states with backoff; server failures surfaced in a dismissable `role="alert"` banner; **run status and connection status are genuinely independent refs**, so a failed run and a disconnected browser are cleanly distinguished. The `localStorage` defect is fixed and tested: a saved run is cleared when an error frame ends it, dropped when it already finished, dropped when the server can no longer serve it, and the page still renders when site data is blocked (`runRecovery.spec.ts`). Missing: **guardrail exhaustion has no representation anywhere in the frontend** — nothing in `frontend/src` mentions it; tool failures get only the generic error treatment; unattributed events are labelled "System" in the rail even though the graph node counts them; evidence-thin `NEEDS_WORK` ends green only incidentally, not by any implemented rule. |

#### Delivery, quality, and operations

| Feature | Status | Evidence, and what is missing |
|---|---|---|
| F40 Headless Validator CLI | **Complete** | `validate` entry point in `pyproject.toml` with `--idea`, `--no-gates`, `--resume`, `--feedback`, `--namespace` and `--feasibility-cache`; dependency-injected crew factories keep it testable with no spend (`tests/validator/test_flow.py::test_validate_headless_entry_point_uses_injected_factories`). The last gap is closed: **concurrent branch output is prefixed with node names** — a ContextVar-scoped stdout wrapper writes `[node_id]` ahead of whole lines only, buffering partial writes per prefix, and any writer outside a branch (the service, another thread) sees an empty prefix and is untouched. |
| F41 Service Entry Point and Environment | **Partial** | `serve` entry point; the `service` extra is installed in `.venv`; `.env` loads from the package path with `override=True`; startup asserts every model constant and every YAML `llm`/`function_calling_llm` uses the `openrouter/` prefix **before FastAPI is imported**. Tests: `tests/service/test_app.py::test_startup_rejects_non_openrouter_model_constants`, `tests/validator/test_crews.py::test_owned_implementation_has_no_openai_model_string`. **`SYNTHETIC=1` now selects no-cost doubles from the console script** — uvicorn can only import a factory *by name* and a string factory drops kwargs, so `serve` could previously build **only** the paid runners, meaning anyone who started the service to look at the UI spent real OpenRouter and Firecrawl credit on the first Launch. `app_from_env()` reads the variable; `tests/service/test_serve_env.py` (5 tests) covers the spellings an operator writes, that unset builds the paid runners, that set builds the doubles, and that `serve` points uvicorn at the env-aware factory. Divergence, unchanged: `PYTHONIOENCODING=utf-8` is **not set** anywhere in `render.yaml`, the `Dockerfile` or CI; the equivalent is achieved by reconfiguring `sys.stdout`/`sys.stderr` at package import, which is stronger for the CLI but does not cover a subprocess. Also unchanged, and the reason this is not Complete: nothing distinguishes the two modes **in the UI**, so a synthetic service is visually indistinguishable from a real one. |
| F42 Performance Validation | **Partial** | Upgraded from Not started because the harness now exists and is itself tested: `scripts/bench_fanout.py` (parallel and sequential arms, gate reply-to-resume probe, RSS sampling at `VALIDATOR_PERF_SAMPLE_INTERVAL_S`, JSON + text output, non-zero exit on a missed target), `scripts/perf_arms.py`, `scripts/perf_metrics.py`, and **58 tests in `tests/perf/`**. Targets are constants, not prose: `VALIDATOR_PERF_TARGET_FANOUT_SPEEDUP = 1.8`, `VALIDATOR_PERF_TARGET_PEAK_RSS_BYTES = 400 MB`, `VALIDATOR_PERF_TARGET_GATE_RESUME_MS = 500`, `VALIDATOR_PERF_RUNS_PER_ARM = 5`. **Not Complete, and this is the clearest case in the file: the measurement has never been taken.** No live five-parallel/five-sequential comparison, no speedup figure, no peak-RSS number, no gate-latency number. Synthetic mode measures orchestration overhead only and reports its speedup as advisory, because there the ratio is a property of `--branch-seconds`. `tests/validator/test_flow.py`'s `ConcurrencyTracker.maximum == 3` is a structural fact, not a speedup. |
| F43 Correctness and Regression Tests | **Partial** | Verified: repeatable verdict bands from identical evidence (by construction, `test_schemas.py`), gapless frame sequences, no event leakage across concurrent runs (`test_spine.py::test_concurrent_contexts_do_not_leak_frames`, now discovered), reconnect, duplicate reply over both transports, restart recovery, post-gate attribution, gate timeout (`test_gate_expiry.py`, 12 tests) and that every router exposes statically inferable labels. **Brief Crew regression is now covered** — `tests/test_brief_crew_regression.py` (23 tests) pins the cache router's contract including that it makes no LLM call, the `Literal` annotation and both statically visible branches, the age helper's refusal to treat unparseable stamps as fresh, the usage-record shape, `persist`'s markdown and run record, Track A owning the retrieval tool while Track B does not, the scrape tool's name and `result_schema`, and `run_crew()`/`kickoff()`. **A browser-level regression suite now exists** — `frontend/e2e/studio.spec.ts`, **7** Playwright tests over a real Chromium, a real WebSocket and a real FastAPI service: the fixed topology (14 nodes, 16 edges), that the page reached the live backend rather than falling through to its mock, both durable gate round trips, the verdict gate's read-only `derived` contract, a Revise reply, and reload recovery. It runs against its own `SYNTHETIC=1` backend on a second Vite server (`e2e/vite.e2e.config.ts`), so it can never launch a paid run. **Updated 2026-09-02:** `studio.spec.ts` is one of **four** e2e files now — 28 tests in total, and **7 of the 28 carry `@launch`**, five of them here. The row previously read "7 Playwright specs … the five run-launching specs", which described this file alone and was true of a suite that no longer exists; and the `@launch` contract now has a hole, because `e2e/builder.spec.ts` launches a run over HTTP and is untagged (see the debt table). **Not in CI** — verified 2026-09-02 by reading `.github/workflows/ci.yml`; the job would need that backend started alongside it, with `SYNTHETIC_BRANCH_DELAY_SECONDS=5`, plus a browser download. **Still not verified: zero fabricated citations across an acceptance set** — no acceptance set exists. *This clause used to add "and no live run has been made"; that is no longer true — one paid run has happened (caveat 4) — but it produced a truncated report over two empty branches and was never inspected for citation closure, so the criterion is exactly as unmet as before.* |
| F44 Deployment Readiness | **Partial** | Health and readiness endpoints report per-dependency status and return 503 when storage is unhealthy; `DATABASE_URL` is honoured with `postgres://`/`postgresql://` normalised to `postgresql+psycopg://`; the frame writer flushes on close via the FastAPI lifespan; credentials stay within the provisioned set with an optional `GITHUB_TOKEN`. **Deployed 2026-08-30** — `agentic-crew-ai-api` (Render web, `python`, `starter`, singapore), `agentic-crew-ai-web` (static), and the **pre-existing** `agentic-crew-ai-db` (PG 18, singapore) **reused rather than recreated**, all from the public repo `simonraj79/multi_agent_crewai_startup_advisor` on `main` with autoDeploy on. Both services now run **`e539811`**. Verified against the deployed origin: `/healthz` → 200; `/readyz` → `"backend": "postgresql"`; the graph endpoint serves 14 nodes / 16 edges; CORS echoes the allowed origin and 400s a disallowed preflight; `wss://…/ws` completes a 101 upgrade; the admission bounds fire in production (an oversized body → **413**, a 2001-character idea → **422**); `/docs` → **404**; and a **2-of-2 read-only Playwright smoke test** passes against the deployed console under `--grep-invert @launch`, so nothing spent money. **No new environment variable had to be set on Render for the hardening to take effect** — every admission knob has a working default and the strict behaviours (`EXPOSE_API_DOCS` off, the bounds on) are the defaults. Cross-origin access is new and tested at `tests/service/test_cors.py` (16 tests — parsing, normalisation, de-duplication, the trailing-slash and URL refusals *with the corrected value in the message*, the wildcard alone but never alongside names, credentials off, refusal at import, preflight granted and refused, an unlisted origin getting no header, the empty default admitting nobody, ETag exposed to cross-origin readers, and that the **WebSocket handshake is not governed by CORS**). Not Complete, and the remaining clauses are specific: **`render.yaml` was never applied** — the services were created through the Render API, so nothing links them to the manifest — the `Dockerfile` has never been built, `maxShutdownDelaySeconds` has never been *observed* protecting a run, no persistence flush has been seen on the target, and **no run has ever *finished* against the deployed service** — two were launched from the console on 2026-08-30 (`e0b3b65e…`, `8b5a0a78…`) and both stopped at the scope gate on one LLM call each. ⚠️ **The trailing clause this row used to carry — "so no research branch, verdict or report has run against live services" — is struck**, and for the same reason as caveat 4 above: `aa7bdc1` records a paid run that reached a verdict and a report, and says its output existed only "on ephemeral container disk", which places it on a deployed instance. Which run that was is not recorded anywhere, so what is honestly unproven here is not that no run finished but that **no *acceptance* run has been inspected end to end**. |

#### The flow builder — outside the PRD feature set entirely

Added 2026-09-02. Nothing here has an F-number, because `PRD.md` does not
describe it; the contract it was built against is
[`docs/flow-builder-spec.md`](../docs/flow-builder-spec.md), and CLAUDE.md is
the handoff. It is recorded in this file for the same reason the two hardening
rows below it are: **it changed what the product is**, and this is the only
document that tracks whether a thing is finished.

Rows use the same status meanings as everything above, including the strict one:
*Complete means a criterion that a machine checked.*

| Item | Status | Evidence, and what is missing |
|---|---|---|
| B01 Canvas document and structural bounds | **Complete** | `builder/document.py` parses `builder.flow/v1`; `builder/bounds.py` refuses what cannot run. Seven node kinds (`input`, `agent`, `crew`, `gate`, `router`, `transform`, `output`) and two tiers (`cheap`, `escalation`). Bounds are `config.py` constants, not inline: `MAX_GRAPH_NODES` 24, `MAX_BILLABLE_NODES` **13**, `MAX_ESCALATION_NODES` **8**, `MAX_FANOUT_WIDTH` 4, `MAX_CYCLES` **3**, `MAX_CYCLE_ITERATIONS` 3. Tests: `tests/builder/test_document.py` (47), `test_bounds.py` (57). |
| B02 Compilation to `crewai.flow/v1` | **Complete** | `builder/compiler.py::compile_document` emits a declaration CrewAI loads. One canvas gate compiles to **two** methods — a `human_feedback` pause and a paired deterministic `@router` — because a single method that does both returns a `HumanFeedbackResult`, which is not a valid event name, so neither branch fires and the run ends silently having produced nothing. Every loop-closing node is a router, for the multi-event `or_()` suppression recorded in CLAUDE.md items 34/35. Tests: `tests/builder/test_compiler.py` (67), `test_from_document.py` (39), `test_gates.py` (36). |
| B03 Code-execution containment | **Complete** | The document carries **no `ref`, no module path and no Python**. Every `do.ref` is picked by the compiler from `BUILDER_ACTION_REFS` — ten entrypoints, nine in `builder/runtime.py` plus `builder/gates.py:GATE_PROVIDER` — and `assert_action_refs` re-checks the **emitted** definition against that frozenset; `call: "script"` is never emitted. Author data travels in `with:` as values. This is the mitigation, and it is asserted on the output rather than trusted at the input. |
| B04 Platform rules hold for a compiled graph | **Complete** | Prompts stay in YAML: a document names an agent id from `BUILDER_AGENT_LIBRARY` (six), each bound to a `config/agents.yaml` entry and its `config/tasks.yaml` task, and there is no document field that carries prompt text. Models stay in `config.py`: a node declares a *tier*, and `runtime._model_for` resolves `CHEAP_MODEL` / `ESCALATION_MODEL`. Gates emit `llm: null` explicitly, because the schema default is the string `"gpt-4o-mini"` — an omitted key would be a paid non-OpenRouter client per gate, a platform-rule violation by omission. Tests: `tests/builder/test_compiler.py`, `tests/service/test_graph_crew_binding.py` (17). |
| B05 Budget layer | **Complete** | `builder/budget.py::estimate_budget` prices a document before it can be published; `MAX_RUN_COST_USD` (default **$10.00**) is the ceiling and `MAX_RUN_COST_USD=0` the deliberate escape hatch. **The bound raise opened no money hole, and this is the interesting part**: `MAX_BILLABLE_NODES` went 8→13, `MAX_ESCALATION_NODES` 5→8 and `MAX_CYCLES` 2→3, and the worst shape those counts now permit prices at **$21.62** against the $10 ceiling — refused **by price**, not by count. (That figure is regenerated by the command in CLAUDE.md section 14, which owns it; this row said **$16.01** until 2026-09-02, flatly and with no caveat, and $16.01 reproduces from no shape.) The counts bound *shape*; the budget layer bounds *money*. Fan-out width stayed 4 deliberately. Tests: `tests/builder/test_budget.py` (30), `tests/service/test_cost_ceiling.py` (25). |
| B06 Builder API | **Complete** | `service/builder_api.py`: `GET /api/builder/vocabulary`; `GET` and `POST /api/builder/workflows`; `GET`, `PUT` and `DELETE /api/builder/workflows/{id}`; `POST /api/builder/validate`; `POST /api/builder/workflows/{id}/publish`. Tests: `tests/service/test_builder_validate_and_history.py` (18). |
| B07 A published graph runs | **Partial** | `service/builder_runner.py` executes through `Flow.from_declaration` and resumes through `Flow.from_pending(..., definition=…)`; `service/builder_rehydrate.py` restores published graphs across the restart that `autoDeploy: yes` guarantees on every push to `main` (`BUILDER_REHYDRATE_PUBLISHED`, default on). Gates open on the **author's own canvas node id** rather than the compiled `n1_confirm`, and carry the label and editable fields the author declared. Cancel reaches CANCELLED. Tests: `tests/service/test_builder_runner.py` (17), `test_builder_gates.py` (34), `test_builder_rehydration.py` (19), and `e2e/builder.spec.ts` publishes a graph and launches it for real over HTTP. **Partial for one reason: every one of those runs is `SYNTHETIC=1`.** No published builder graph has ever completed against paid models, so the estimate has never been checked against a bill. |
| B08 Builder console | **Complete** | Counted at head 2026-09-02: `frontend/src/components/builder/` holds **34 files — 33 `.vue` plus `commit.ts`** — across the directory and its `fields/` and `inspectors/` subdirectories; **seven** `useBuilder*` composables; `types/builder.ts`; `services/builderApi.ts`; and **five** data modules (`nodeKinds`, `builderDefaults`, `builderVocabulary`, `builderTemplates`, `builderRunHandoff`). Palette, canvas, docked inspector, budget meter, problems dock, minimap, template gallery, publish dialog — **docked, never modal**. Route `#/build` through a hash router in `composables/useWorkspaceRoute.ts`, **108 lines** (the handoff called it 60; `wc -l` says 108, and the measurement wins) — **no `vue-router`**. **Zero new npm dependencies**, verified rather than asserted: `git diff 4d70cbf..6d2743c -- frontend/package.json` is empty. Tests: **16** builder spec files under `frontend/tests/` (`ls frontend/tests/builder*.spec.ts | wc -l` — the 18 published here until 2026-09-02 reproduced from no counting method), plus `e2e/builder.spec.ts` (15) and `e2e/builder-layout.spec.ts` (3). |
| B09 The evaluator as a template | **Complete** | `frontend/src/data/templates/ideaValidator.ts` expresses the six-agent evaluator as a `BuilderDocument`: **16 nodes, 22 edges** (counted at head 2026-09-02 from the `NODES` and `EDGES` literals), `joins: {score: 'all'}`, two revise loops closed through router nodes, `input_field: "idea"`. Recorded live against `POST /api/builder/validate`: `valid: true`, 0 problems, static **$1.5137** / floor **$1.2159**, 8 billable, 5 escalation, 2 cycles, ceiling $10.00, `over_ceiling: false` — **those budget figures are the handoff's measurement, not this pass's**; this pass counted the nodes and edges and did not re-run the validate call. The file's own docblock records that the derived *graph descriptor* has 17 nodes where the document has 16, and why. It carries a caveat rendered verbatim on its gallery card: this is the evaluator's **shape**, not its judgement — the rubric, the confidence arithmetic, the guardrails and the warm cache live in Python. |
| B10 Client/server problem-code mirror | **Complete** | `PROBLEM_CODES` in `frontend/src/types/builder.ts` mirrored the server at **27** codes where the server emits **30**, and its anti-rot test read two of the **three** Python files that declare them — so the mirror agreed with *itself* at the wrong number. The missing `library-missing-prompt-input` is the most common problem in the builder, because a fresh agent node defaults `prompt_inputs: {}`. Guarded from both ends now: `tests/builder/test_problem_code_declarations.py` (4) forbids the inline-literal spelling the frontend's grep cannot see, and `tests/builder/test_client_fixtures.py` (8) regenerates both committed fixtures in memory and byte-compares (normalising line endings, because `core.autocrlf` is `true` here and a raw compare would report the platform instead of the drift). Verified at head 2026-09-02: `builderProblemCodes.json` carries **30** codes and `src/types/builder.ts` lists **30**. |
| B11 Sprites | **Removed, deliberately** | 144 ChatDev character PNGs were sourced, downscaled 91%, licensed under Apache-2.0, rendered on every node — **and then removed**. Rendering them is what showed that nothing writes a design-time run state, so **132 of 144 frames could never paint** while every template open still fetched ~191 KiB of them; that spec §5.7 reserves the slot and forbids a design-time animation in it; and that the art is the competitor's, which is a strange thing to ship in the product whose argument is that it is not that competitor. Nothing sprite-shaped remains in the tree. This is *not* a resolution of **F34** above, which is about the validator console — but it is the same decision reached with evidence, and F34's row should be read against it. *Verified in-tree 2026-09-02: `grep -ri sprite frontend/src` returns **two comments and no asset**, and `BuilderNode.vue:408-418` carries the whole reasoning at the empty slot — "132 of the 144 PNGs were unreachable", "195,832 bytes of frames 2 and 3 for a first stride that cannot occur", spec §5.7 reserving the slot, and the competitor's art. Twelve characters, 144 frames. The import and the downscale are the builder work's own record; the removal and its reasons are checkable from the source.* |

**The two legibility losses, and the one cause.** An independent design critic
scored the builder against the real ChatDev (`D:/ChatDev-main`) across 13
dimensions at **93 to 61** — winning 10, tying 1, losing 2. Both losses were
legibility, with one cause: a 720×1480 template against a 1.69:1 pane forces the
fit to 0.478 and 7.2 px titles. Re-laid to 1720×980: fit 0.695, titles 10.4 px,
85% of the canvas width used, nothing clipped. The comparison screenshots under
`docs/comparison/` are **deliberately not committed** — they are captures of a
third-party product, and the global `*.png` ignore rule already excludes them.
That last part *was* checked here, and checked the way this repo insists
(`git check-ignore -v`, never by reading `.gitignore`): `docs/comparison/`
exists with `chatdev/` and `ours/`, `git ls-files docs/comparison/` returns
nothing, and `git check-ignore -v docs/comparison/*.png` answers
`.gitignore:58:*.png`. **The scores and the pixel figures were not re-measured;
they are the critic's, and the screenshots cannot be checked from the
repository.**

#### Hardening outside the PRD feature set

Neither row below is a numbered PRD feature. Both are recorded here because they
changed the documented API surface or the meaning of a green suite, and this file
is where that is supposed to be visible.

| Item | Status | Evidence, and what is missing |
|---|---|---|
| Public-API admission control | **Complete** | ⚠️ *The premise of this row's first clause expired on 2026-09-01.* The endpoint is **no longer unauthenticated**: Google sign-in through Better Auth landed, and `VALIDATOR_REQUIRE_AUTH` defaults to `bool(AUTH_BASE_URL)` so configuring an auth server *is* turning auth on. The bounds below all still exist and are all still tested — admission control was never redundant with a login, and a signed-in client can still flood — but read "unauthenticated by design" as history, not as the current posture. Original text follows. The deployed endpoint is unauthenticated by design — a login would end the open demo — so `POST /api/sessions/{sid}/runs` is bounded instead. Body over `MAX_REQUEST_BODY_BYTES` (64 KiB) → **413** from a pure-ASGI middleware reading the declared `Content-Length`, before FastAPI or pydantic touches it (`service/app.py::RequestBodySizeLimitMiddleware`, added *inside* CORS so a 413 still carries CORS headers); over the per-client bucket → **429** with a computed `Retry-After`; at `MAX_QUEUED_RUNS` → **429** with `Retry-After: 30` (429 not 503 — nothing is broken); `inputs.idea`/`inputs.topic` over `MAX_RUN_INPUT_CHARS` (2000) → **422** naming the field and the actual length; `inputs` over `MAX_RUN_INPUT_BYTES` (8 KiB) or `MAX_RUN_INPUT_KEYS` (16) → **422** from `service/models.py`. `/docs`, `/redoc` and `/openapi.json` are **404 unless `EXPOSE_API_DOCS=1`** or the app is synthetic — logged in `config.py` as obscurity, not a control. Two carve-outs are deliberate and both are tested: a run **waiting at a gate holds no admission slot** (it has already returned its worker thread), and a **gate reply is never refused for capacity** (refusing one would strand a human mid-run). Tests: **`tests/service/test_run_admission.py` (37)** — bucket burst/refill/thread-safety/per-client isolation/`0` disables it, the `X-Forwarded-For` key and its length bound, every input bound including exactly-at-the-bound, the body limit and that it leaves ordinary requests alone, capacity returned on completion, `/healthz` and read-only `GET`s never limited, and that hiding the docs does not hide the API. Honest limit, stated in `config.py` and not softened here: **the rate limiter is a courtesy control, not a security one** — in-process, one instance, resets on deploy, multiplies if scaled out, and keyed on a header the client writes. `MAX_QUEUED_RUNS` is the keyless bound that actually holds. |
| Suite runs on a clean checkout / CI green | **Complete** | `tests/__init__.py` `setdefault`s two obviously-fake placeholders for `OPENROUTER_API_KEY` and `FIRECRAWL_API_KEY` before anything imports `brief_crew`, whose `__init__.py` calls `load_dotenv(override=True)` at import time. Without them ~40 tests that *construct* real `LLM` and Firecrawl objects to assert their wiring failed at `__init__` — 4 failures and 36 errors in ~5s — on any machine with no `.env`, which is every CI machine. `setdefault` and never assignment, so a real `.env` still wins; only the two variables an actual failure demands, since `PINECONE_API_KEY`/`COHERE_API_KEY` are injected per-test and `GITHUB_TOKEN` is deliberately *cleared* by `tests/tools/test_github_feasibility.py`. Evidence: run `33293970810` at `e539811`, both jobs `success`, `Ran 415 tests in 15.823s / OK (skipped=1)` — **the first green run in the repository's history**; the three preceding commits are all `failure`. What this does **not** buy, and the reason it appears here rather than closing any row below: CI runs the same doubles, so it is evidence that the suite is portable, not that the product works. The Playwright suite is still **not** in CI. |

### Measurement and verification debt

Carried explicitly so it is not mistaken for completed work.

| Debt | Blocks | Note |
|---|---|---|
| Fan-out speedup, peak RSS, gate reply-to-resume latency | F42 | **Never measured.** The harness and its 58 tests exist; the live run does not. This is the single clearest Partial-not-Complete in the file. |
| Live paid acceptance run + citation-closure set | F43, F05-F08 | ⚠️ **"Never run" was true when this row was written and is not true now.** One paid run happened; it produced a report truncated at 4096 characters, priced at $0.00 over 128,069 tokens, over two empty research branches (caveat 4). All three defects are fixed and **none has been re-exercised live.** So: an *acceptance* run has never been made, no acceptance set exists, and citation closure has never been inspected — every automated thing still uses doubles, `synthetic=True` or `SYNTHETIC=1`, and the market tool's 402/plan-limit branch is still untested. The row does not close. What changed is that the reason it does not close is now "the run that happened does not count" rather than "no run happened". |
| PostgreSQL **under concurrency** | F31, F44 | Narrowed, not closed. The deployed API created its schema against real PG 18 and reports `"backend": "postgresql"`, so the dialect is exercised. Every *automated* test still runs on SQLite, whose single-writer model cannot stress the `UPDATE ... WHERE ...` + `rowcount` compare-and-set that `pending_feedback` and the gate reply both depend on. **Two processes replying to one gate has never been tested.** |
| Deployment behaviours that need a real run | F44 | `maxShutdownDelaySeconds: 300` protecting a run through a redeploy, the persistence flush on `SIGTERM`, and per-run token metrics populating on the host are all unobserved — each needs a run in flight, and a run costs money. |
| Playwright suite in CI | F43, B07, B08 | **28 tests in 4 files now, still not wired up** — verified 2026-09-02 by reading `.github/workflows/ci.yml`, which declares two jobs and runs neither Playwright nor a backend. The job needs `SYNTHETIC=1 PORT=8099 SYNTHETIC_BRANCH_DELAY_SECONDS=5 serve` alongside it plus a browser download. Until then a regression only the browser sees reaches `main` — which is how the paused-gate-node defect got there, and how **both** builder layout defects got there: a 236×70 gallery holding 1356 px of content, and a canvas reporting itself fitted with two nodes under the dock. 988 green unit tests saw neither, because a jsdom mount asserts structure and never asks how wide anything ended up. |
| The `@launch` tag no longer covers everything that launches | F43, B07 | `e2e/builder.spec.ts::walks to a problem from the panel, fixes it, publishes, and the graph launches` does `request.post('/api/sessions/e2e-builder/runs', …)` and is **not tagged**. Its own comment — *"Synthetic runners, so this costs nothing"* — is true of the local backend and is not what the tag is for: the tag exists so the suite can be pointed at a **deployed** origin. Measured 2026-09-02: 7 of 28 carry `@launch`, `--grep-invert @launch` leaves 21, and that 21 includes this one. Tagging it is the fix; nobody has done it. |
| A builder graph has never met paid models | B07, B09 | Everything under M6 runs `SYNTHETIC=1`. The budget layer's estimate has therefore never been checked against a bill, and `MAX_RUN_COST_USD` has never refused a real run. The one time a builder graph did reach real money it raised `TypeError` after four billed nodes — which is the argument for the row above it, not against it. |
| `SYNTHETIC_BRANCH_DELAY_SECONDS` is invisible to the knob inventory | — | The canonical environment-knob scan reads exactly two files, `config.py` and `service/app.py`. This knob is read in `service/runner.py`, so it is in no list. Confirmed 2026-09-02 by grepping `os.getenv(`/`os.environ.get(` across `src/`: five reads sit outside those two files — `SYNTHETIC_BRANCH_DELAY_SECONDS` (`service/runner.py`), `VALIDATOR_CACHE_NAMESPACE` (`validator_cache.py`), and three credentials (`OPENROUTER_API_KEY`, `FIRECRAWL_API_KEY`, `GITHUB_TOKEN`). **The count and the list are [`../docs/tech-stack.md`](../docs/tech-stack.md)'s to own, not this file's** — recorded here only because a required E2E precondition being absent from every inventory is a status fact. |
| `render.yaml` vs the live services | F44 | The manifest was never applied; the two services were created through the Render API. Nothing enforces that the two agree, and nothing warns when they drift. |
| Human review of `RUBRIC_ANCHORS` | F09, F10, F15 | ⚠️ **CLOSED 2026-09-01 by [`docs/rubric-ratification.md`](../docs/rubric-ratification.md)** — the rubric has been ratified, seven changes applied (four Critical), F level 0 and `FLOOR_NOT_BUILDABLE` retired, and the review's "do not spend money" verdict lifted. Two claims in the fourth-pass text below are stale and are corrected there: F4 is **fixed**, not open, and the open questions are settled. *This pass confirmed the ratification file exists at head and did not audit it.* The fourth pass's text is kept below because it is the argument the ratification answers, and because a reader who trusts a closure without reading what it closed has learned nothing. Original text follows. All five ladders are binding and tested; **none has been read by a human.** M/C/F/X are a derivation, and PRD §10.2's own Demand ladder was defective in three ways before it was repaired. An independent adversarial pass now exists at [`docs/rubric-review.md`](../docs/rubric-review.md) — written by an agent with no part in the derivation, which raises the evidence and does **not** close this row. A derivation error is a judgement nobody made; a second agent agreeing is still nobody. See CLAUDE.md remaining-work item 5 for the eight anchors the audit itself was unsure of. **And the review did not merely fail to close this row — it argued the other way**: its verdict is *"do not spend money on a live acceptance run against this rubric as it stands"*, with two **Critical** findings (`FLOOR_ALREADY_FREE` counting only repositories; D=0's `zero_ok = usable >= 1` rejecting on one off-hand comment, non-provisionally) still true at head. This now **gates** the paid acceptance run above rather than merely accompanying it. Nothing in the deployment or CI work touched `RUBRIC_ANCHORS`. |
| Firecrawl plan economics | F05 | Real rate limits and per-credit search+scrape cost unmeasured (PRD Q3). |
| Reporter/Scoper cheap-tier A/B | F13, F02 | Not run (PRD Q4); listed under Deferred Enhancements below. |
| F34 sprite decision | F34 | The vector/icon identity is a deliberate substitution. **Still undecided for the validator console** — but the builder settled the same question with evidence and settled it the other way (B11 above): 144 ChatDev PNGs were imported, rendered, and then removed, because 132 of 144 frames could never paint, the fetch cost ~191 KiB per template open, and the art belongs to the competitor the product argues against. That is not a decision on F34; it is the strongest available input to one. |
| `RUN_CONCURRENCY > 1` observed queueing | F26 | Asserted on the executor's configuration, never on a run that was seen queued and then started. |
| Query-quality validation | F02, F15 | `scope_problems` checks the assumption count and one scoping gap; nothing checks that the generated queries are category-based rather than the pitch plus keywords. |
| Guardrail exhaustion in the UI | F39, F13 | The backend's terminal failure mode has no representation in `frontend/src`, and nothing tests the raise. |

## Platform Requirements

- **CrewAI-native orchestration:** Use CrewAI `Flow`, `Process.sequential`, sibling `@listen` fan-out, deterministic `@router` methods, task guardrails, and native human feedback. Do not introduce LangGraph or a custom orchestration engine.
- **OpenRouter-only model access:** Route every agent, guardrail, and human-feedback model call through the model IDs defined for OpenRouter in `config.py`.
- **No direct OpenAI dependency:** The validator must not require `OPENAI_API_KEY`, must not fall back to CrewAI's default OpenAI models, and must explicitly pass the OpenRouter-backed `CHEAP_MODEL` wherever CrewAI would otherwise choose a default model.
- **OpenRouter embeddings:** Continue calling `brief_crew.embeddings` directly. Do not route embeddings through CrewAI's embedder, and keep `DOC_PREFIX` and `QUERY_PREFIX` paired.
- **Centralized model configuration:** Keep model names, pricing, thresholds, and embedding constants in `config.py`; do not inline them in agents, tasks, tools, or service code.
- **Existing Brief Crew compatibility:** Preserve `run_crew()`, `kickoff()`, `output/brief.md`, `output/last_run.json`, existing prompts, and existing behavior.

## Core Validation Workflow

### F01. Startup Idea Submission

- Accept a one-line startup idea from the Studio or the headless CLI.
- Create a distinct `run_id` under a reusable `session_id`.
- Queue runs when the configured concurrency limit is reached.
- Display queued, running, waiting, cancelling, completed, cancelled, and failed states accurately.

### F02. Structured Idea Scoping

- Run a `scoper` agent on the OpenRouter escalation-tier model with no tools.
- Convert the raw idea into a validated `ScopedIdea` containing the market category, target user, technology claim, branch-specific queries, three to five assumptions, scoping gaps, and an `as_of` date.
- Generate category-based research queries instead of appending generic keywords to the original pitch.
- Pass query lists to CrewAI prompts as joined text blocks rather than Python list representations.

### F03. Scope Confirmation Gate

- Pause after scoping and show all parsed fields in an editable form.
- Let the operator approve the scope or submit revisions.
- Route approve/revise decisions deterministically without an LLM call.
- Persist pending feedback so the run remains resumable after disconnects, timeouts, process restarts, and deployments.
- Mark an unanswered timed-out gate as expired without failing or auto-answering the run.

### F04. Parallel Research Fan-Out

- Launch Market Analyst, Sentiment Analyst, and Feasibility Analyst concurrently as three sibling Flow listeners.
- Keep branch methods synchronous so CrewAI runs them through `asyncio.to_thread` with copied context.
- Use one single-agent Crew per branch so all three nodes appear independently in the live graph.
- Join the branches only after all three have completed.
- Retain a sequential fallback if measurement fails the speed or memory targets.

### F05. Market Landscape Research

- Use an OpenRouter cheap-tier Market Analyst and a Firecrawl search-and-scrape tool.
- Return competitors, pricing, paying segments, market evidence, gaps, source URLs, retrieval time, and tool status in a structured envelope.
- Handle both Firecrawl `Document.url` and `SearchResultWeb.metadata.source_url` response shapes.
- Detect plan limits and rate-limit responses rather than hard-coding an unverified Firecrawl quota.

### F06. Community Sentiment Research

- Use an OpenRouter cheap-tier Sentiment Analyst and the Hacker News Algolia API.
- Search relevant stories, then fetch comment trees for the strongest threads.
- Classify evidence as `HAS_PROBLEM`, `PAYS`, `BUILT_WORKAROUND`, `OPINION`, or `OFF_TOPIC`.
- Capture attributable quotes, recency, points, comment counts, gaps, and tool status.
- Cite the Hacker News discussion URL derived from `objectID`, including Ask HN items with a null `story_url`.
- Detect HTTP 429 responses and back off without assuming rate-limit headers exist.

### F07. Technical Feasibility Research

- Use an OpenRouter cheap-tier Feasibility Analyst and GitHub repository search.
- Capture relevance, license, commercial-use suitability, archived state, recent activity, implementation signals, and evidence URLs.
- Send a valid `User-Agent` on every GitHub request.
- Enforce a shared module-level token bucket: 8 requests/minute without `GITHUB_TOKEN`, 24 requests/minute with it.
- Return `rate_limited` honestly so confidence drops instead of producing a verdict from incomplete evidence.
- Support escalating this agent alone if cheap-model results repeatedly exhibit the star-count fallacy.

### F08. Structured Tool Results and Evidence Closure

- Make every research tool return a JSON envelope with `status`, `tool`, `query`, `retrieved_at`, `result_count`, `results`, and `notes`.
- Require every result to contain a non-empty URL.
- Record the exact URL set returned by tools for the run.
- Reject any finding or report URL not present in that captured set.
- Require failed, empty, or rate-limited tools to produce empty sources and explicit evidence gaps.

### F09. Evidence Synthesis

- Run the `synthesist` on the OpenRouter escalation-tier model with no tools.
- Consume the three branch outputs only after fan-in.
- Assign five anchored integer scores: Demand, Market, Competitive room, Feasibility, and Headroom over free.
- Produce evidence counts, kill criteria, the cheapest next test, and a draft verdict.
- Keep reasoning enabled at an appropriate level; do not copy the evaluator's minimal-reasoning setting into this judgement step.

### F10. Deterministic Rubric and Verdict

- Calculate the composite score mechanically on a 0.0–10.0 scale:

  $$\operatorname{score}=2(0.30D+0.20M+0.20C+0.15F+0.15X)$$

- Compute `composite_score`, `verdict`, `confidence`, `confidence_band`, and `provisional` in a Pydantic model validator rather than trusting model arithmetic.
- Apply the confidence override before hard floors and score thresholds.
- Return `NEEDS_WORK / INSUFFICIENT_EVIDENCE` whenever confidence is below 0.35.
- Apply fatal-dimension floors for no demand, no market, an already-good free solution, and an unbuildable v1.
- Return `VALIDATE` only when the composite is at least 7.0, every dimension is at least 3, and confidence is at least 0.60.
- Return `REJECT` for a composite below 4.0 when no confidence override applies.
- Make two runs over identical evidence produce the same verdict band.

### F11. Mechanical Confidence Scoring

- Compute confidence from market, sentiment, and feasibility coverage, market-source staleness, and branch completion.
- Use confidence bands: HIGH at 0.70 or above, MODERATE from 0.35 to 0.69, and LOW below 0.35.
- Apply a 0.60 branch penalty whenever fewer than three research branches succeed.
- Label REJECT outcomes between 0.35 and 0.60 confidence as provisional in both the title and summary.
- Prevent LOW-confidence reports from using unjustifiably certain wording.

### F12. Verdict Review Gate

- Pause after synthesis and show the rubric, draft verdict, confidence value, confidence band, evidence gaps, and cheapest next test.
- Let the operator approve or revise the verdict inputs.
- Route button decisions deterministically with zero LLM calls.
- Preserve structured operator overrides for the reporter and audit log.

### F13. Validation Report Generation

- Run the `reporter` on the OpenRouter escalation-tier model initially, with a later cheap-tier A/B option.
- Produce a sourced Markdown report with verdict, confidence, score table, evidence, risks, kill criteria, cheapest next test, gaps, and sources.
- Write the final body to `output/validation.md` from the Flow persistence step.
- Keep `output_pydantic` on the task but omit `output_file` so CrewAI does not write JSON into the Markdown file.
- Fail the run rather than publish a report that exhausts its citation guardrail retries.

## Schemas and Guardrails

### F14. Pydantic Validation Models

- Add flat leaf models for `Evidence`, `Competitor`, `Thread`, `Repo`, and `DimensionScore`.
- Add stage models for `ScopedIdea`, `MarketFindings`, `SentimentFindings`, `FeasibilityFindings`, `Verdict`, and `ValidationReport`.
- Keep nesting to one level where practical to avoid repeated structured-output retries.
- Validate URLs with actionable field-validator messages while storing them as strings.
- Include countable `source_urls` fields and verify that they match nested source objects.

### F15. Zero-Cost Mechanical Guardrails

- Validate scope completeness and query quality.
- Validate branch status honesty, URL closure, source/list count consistency, and required gaps.
- Validate exact rubric anchor selection and reserve score 1 for insufficient evidence.
- Recompute every count used by the confidence calculation.
- Validate report structure, confidence language, and provisional labels.
- Parse the first guarded task attempt from `TaskOutput.raw`, return successful raw text unchanged, and allow Pydantic conversion afterward.

### F16. Citation Judgement Guardrail

- Run one OpenRouter-backed LLM citation guardrail on the reporting task after mechanical checks pass.
- Do not attach paid string guardrails to the three parallel research tasks.
- Surface the final guardrail error as a terminal UI state rather than as a socket disconnect.

## Cache and Retrieval

### F17. Branch-Level Warm Cache

- Look up cached evidence only after the operator confirms the scoped category.
- Use the cache for market evidence, never for sentiment, and optionally for feasibility as a GitHub rate-limit shock absorber.
- Use branch-specific relevance and freshness thresholds.
- Run every research branch even when cached evidence exists; cached passages supplement live evidence and never skip validation work.
- Label cached evidence with retrieval and source dates.

### F18. Safe Evidence Indexing

- Index one document per source URL with `branch`, `category`, `idea_hash`, publisher, and timestamps.
- Add metadata filtering by branch and category to retrieval.
- Use a per-user Pinecone namespace.
- Permit only source evidence at the indexing boundary.
- Reject `ScopedIdea`, `Verdict`, and `ValidationReport` objects to prevent conclusions from becoming evidence.

## Live Event and Observability Spine

### F19. Ordered CrewAI Event Capture

- Capture events through a per-run ContextVar-scoped stream sink, with async event listeners as a fallback.
- Never register plain synchronous bus handlers for UI sequencing.
- Keep capture handlers constant-time, non-blocking, exception-safe, and free of network or database I/O.
- Re-establish run context and the stream sink before every human-feedback resume.
- Ignore events from ordinary Brief Crew CLI runs when no UI or Flow run context is active.

### F20. Versioned Frame Protocol

- Emit `{type: "frame", data: {...}}` messages with protocol version, gapless per-run sequence, run ID, timestamp, kind, event type, level, node ID, message, bounded details, and duration.
- Support `run_state`, `node_state`, `edge_taken`, `agent`, `tool`, `llm`, `token`, `gate_open`, `gate_closed`, `metrics`, and `error` frame kinds.
- Map CrewAI method, task, agent, tool, model, token, and human-feedback events field by field.
- Never serialize entire CrewAI objects or call `event.to_json()`.
- Emit a structured `edge_taken` frame rather than parsing human-readable log strings.

### F21. Stable Node Attribution

- Declare stable node IDs in the graph descriptor.
- Resolve events by task name, agent-role template prefix, current Flow method, then a visible `Unattributed` quarantine node.
- Keep each fan-out branch independently attributable.
- Count unattributed frames and expose the count in run status.

### F22. Token Streaming and Call Timing

- Stream model chunks without blocking the model thread.
- Show one loading bubble per active node.
- Add live timer chips for model and tool calls using before/after event pairs.
- Freeze elapsed durations when a node finishes.

### F23. Per-Run and Per-Node Usage Accounting

- Accumulate prompt tokens, completion tokens, calls, latency, and cost by `(run_id, node_id, OpenRouter model)`.
- Price model calls through `compute_cost_usd()` and the centralized OpenRouter price table.
- Show per-node and total usage in the UI.
- Compare event-derived totals with `Flow.usage_metrics` and log discrepancies rather than silently selecting one.

### F24. Bounded Backpressure

- Keep a 2,000-frame per-run ring buffer and count dropped oldest frames.
- Give each WebSocket subscriber a bounded queue of 512 frames and count drops.
- Perform database writes in a separate batched writer, never in an event handler.
- Expose frame count, dropped count, and emit errors through run status.

## Backend Service

### F25. Workflow and Graph APIs

- `GET /api/workflows` returns registered workflows.
- `GET /api/workflows/{id}/graph` returns a versioned `GraphDescriptor` with an ETag.
- Derive topology from CrewAI's `build_flow_structure()` and enrich it with fixed layout metadata.
- Validate overlay keys and require every router to expose statically inferable events at service startup.
- Correct the existing Brief Flow router return annotation so cache-hit and cache-miss edges appear in the graph.

### F26. Run Lifecycle APIs

- `POST /api/sessions/{sid}/runs` starts or queues a run and returns HTTP 202 with `run_id`, status, and graph version.
- `GET /api/runs/{rid}` returns status, pending gate, frame counters, errors, and usage.
- `GET /api/runs/{rid}/frames` supports `after`, a maximum `limit` of 500, and kind filtering.
- Keep `run_id` distinct from `session_id` so one session can contain multiple runs.

### F27. Human Gate APIs

- `POST /api/runs/{rid}/gates/{gid}` accepts structured approve/revise replies over HTTP.
- Accept gate replies over WebSocket as well.
- Return HTTP 409 when a gate has already been answered.
- Return pending gate state through run status so reconnecting clients can recover it independently of the socket replay.

### F28. Cooperative Cancellation

- `POST /api/runs/{rid}/cancel` marks the run as cancelling.
- Use per-run scoped `PRE_STEP` hooks that raise `HookAborted` at the next Flow-method or task boundary.
- Report cancellation granularity explicitly: an active model or tool call may finish before stopping.
- Keep the UI in “stopping after the current step” until the server confirms cancellation.

### F29. Log Export

- `GET /api/runs/{rid}/logs` exports NDJSON or ZIP.
- Include ordered frames, gate interactions, node timings, usage, cost, tool status, and terminal errors.
- Make log download available from the Studio controls.

### F30. Reconnecting WebSocket

- Serve `/ws?session_id=&run_id=&after=`.
- Support ping/pong, retry with backoff, sequence-based replay, deduplication, and session TTL cleanup.
- Replay durable frames after reconnect and expose any sequence gaps.
- Ensure a slow or disconnected client cannot delay a CrewAI run.

### F31. Durable Run Persistence

- Store runs, run metrics, node metrics, frames, gates, session IDs, workflow IDs, flow IDs, and graph versions in Postgres.
- Implement `PostgresFlowPersistence` for CrewAI state and pending feedback.
- Batch frame persistence approximately every 250 ms from one writer task.
- Preserve resumability across Render restarts and deployments.
- Limit active runs to `RUN_CONCURRENCY=1` on the target 512 MB Render instance and queue additional runs.

## Studio UI

### F32. Three-Pane Validator Studio

- Build the Studio with Vue 3, Vite, and Vue Flow.
- Fill the viewport with a live graph canvas, collapsible chat rail, and controls/status panel.
- Support Chat and Graph view modes.
- Adapt the layout for tablet widths; mobile layout is out of scope.

### F33. Fixed Live Agent Graph

- Render Scoper, three research analysts, Synthesist, Reporter, gates, start/final states, and a visible Unattributed node.
- Use stable positions and a fixed topology rather than a graph editor.
- Provide pan, zoom, fit, and lock controls.
- Represent idle, running, waiting, completed, and error states distinctly.
- Keep dimensions stable so status labels and animations do not shift the layout.

### F34. Node and Sprite Identity

- Use deterministic agent-to-palette assignments from the fixed roster.
- Use deterministic hash-based sprite assignment so each agent keeps the same avatar across graph, chat, and reloads.
- Downscale source sprites to 64×80 assets.
- Animate the active agent with the two-frame walk cycle and stop animation for waiting, completed, and error states.

### F35. Edge and Handoff Visualization

- Animate active handoffs from structured `edge_taken` frames.
- Pulse edges during execution and show clear condition labels.
- Use Vue Flow Bezier paths plus one explicit self-loop case.
- Animate a sprite along the traversed path with duration based on path length.
- Keep shared SVG definitions global rather than duplicating them per edge.

### F36. Live Chat Rail

- Stream agent, tool, model, system, warning, error, and human-interaction entries with timestamps and stable avatars.
- Use collapsible long messages with an accessible Show More/Show Less control and `ResizeObserver` support.
- Display structured tool and model activity as timed chips.
- Preserve readable per-node attribution while the three branch crews run concurrently.

### F37. Gate Interaction Cards

- Render scope confirmation as editable structured fields.
- Render verdict review with the rubric, confidence, evidence gaps, and proposed outcome.
- Show waiting and expired states on both the node and the card.
- Restore the active card after reconnect, refresh, timeout, or deployment.

### F38. Run Controls

- Provide workflow selection, read-only status, Chat/Graph segmented control, Launch/Send/Relaunch primary action, Cancel, and Download Logs.
- Make Relaunch immediately start a new run with the current idea.
- Await server confirmation before showing a run as cancelled.
- Use icons for familiar graph, collapse, zoom, fit, lock, download, settings, and cancellation actions, with tooltips where needed.

### F39. Error and Recovery UX

- Render tool failures, guardrail exhaustion, frame drops, unattributed events, disconnects, and server failures explicitly.
- Preserve the last server-confirmed state during reconnect.
- Distinguish a failed run from a disconnected browser.
- Show evidence-thin results as valid `NEEDS_WORK` outcomes rather than degraded failures.

## Delivery, Quality, and Operations

### F40. Headless Validator CLI

- Add a `validate` entry point that runs the validator without the frontend.
- Keep the validator testable before the service and UI are complete.
- Prefix concurrent branch output with node names so terminal traces remain readable.

### F41. Service Entry Point and Environment

- Add a `serve` entry point for FastAPI and WebSocket hosting.
- Install the existing `service` optional dependency group in the isolated `.venv`.
- Set `PYTHONIOENCODING=utf-8` in the service environment.
- Preserve `.env` loading from the package path with `override=True`.
- Add startup validation that all resolved LLMs use configured OpenRouter models and no CrewAI object falls back to an OpenAI model.
- Let `serve` start the no-cost doubles from the environment (`SYNTHETIC=1`), so starting the application to look at it cannot spend money.

### F42. Performance Validation

- Compare five parallel and five sequential research runs.
- Require at least 1.8× fan-out speedup or withdraw the parallel implementation.
- Keep peak resident memory below 400 MB on a 512 MB target.
- Keep gate reply-to-resume latency below 500 ms.

### F43. Correctness and Regression Tests

- Verify zero fabricated citations across the acceptance set.
- Verify repeatable verdict bands from identical evidence.
- Verify gapless frame sequences and matching node-start/node-end pairs.
- Verify no event leakage across concurrent runs.
- Verify gate timeout, reconnect, duplicate reply, restart recovery, and post-gate event attribution.
- Verify Brief Crew behavior and output remain unchanged.
- Verify every router has statically inferable output labels.
- Drive the operator journey in a real browser against a real service — launch, both gates, completion — with the run-launching cases tagged so a deployed smoke test can exclude them and stay free.

### F44. Deployment Readiness

- Run the service with Postgres-backed state and frame history.
- Set a shutdown delay sufficient for active steps and persistence flushing.
- Expose health and run-status information needed by the hosting platform.
- Keep paid credentials limited to the already provisioned OpenRouter, Firecrawl, Pinecone, and Cohere keys; support an optional GitHub token.
- Allow the deployed console's origin to call the API, by name and by default nobody (`CORS_ALLOW_ORIGINS`), refusing a malformed value at startup rather than shipping a rule that silently matches nothing.

## Delivery Order

1. **M-1: Prerequisites** — repair the Brief Flow graph annotation, prove ordered event capture, and implement Postgres Flow persistence.
2. **M0: Event spine** — emit ordered, attributable frames from the existing Brief Flow.
3. **M1: Service** — expose graph, run, frame, gate, cancellation, log, and WebSocket APIs.
4. **M2: Read-only Studio** — visualize an existing Brief Crew run with live nodes, edges, and chat.
5. **M3: Validator crew** — add all six agents, tools, schemas, rubric, guardrails, CLI, and measured fan-out.
6. **M4: Human gates** — complete scope and verdict pause/resume, timeout, reconnect, and recovery.
7. **M5: Hardening** — finish per-node cost, durable logs, cancellation, acceptance tests, and spec reconciliation.

**M6 is not on this list, and that is not an oversight.** The flow builder was
never in `PRD.md`'s delivery order because it was never in `PRD.md`; it was
specified separately in [`docs/flow-builder-spec.md`](../docs/flow-builder-spec.md)
and merged on 2026-09-02. It is tracked in the milestone table and in
[its own section](#the-flow-builder--outside-the-prd-feature-set-entirely), and
it depends on M1 and M2 having landed — it publishes into the same registry and
draws on the same console shell. Nothing in M0–M5 depends on it.

## Explicit Non-Features

> ⚠️ **The first line below is FALSE as of 2026-09-02 and has been struck rather
> than deleted.** A non-feature that shipped is the most misleading kind of
> stale line in a status document, because nothing about it looks stale: it
> reads as a decision, not as a measurement, so nobody re-checks it. The rest of
> this list was re-read against the tree in this pass. **Two** of the ten lines
> are now false; both are struck inline and neither is deleted.

- ~~No graph editor or user-authored workflow YAML.~~ **Superseded.** There is a
  graph editor at `#/build`, and a user authors a `builder.flow/v1` document
  that compiles to `crewai.flow/v1`. What survives of the original intent is the
  part that mattered: **the author never writes YAML and never writes code.**
  The document is JSON with a closed vocabulary, prompts stay in
  `config/agents.yaml` and `config/tasks.yaml` where a document can only *name*
  one, and the only code a compiled graph can run is the ten entrypoints in
  `BUILDER_ACTION_REFS`. See [The flow builder](#the-flow-builder--outside-the-prd-feature-set-entirely).
- No LangGraph dependency.
- No manager or hierarchical orchestration agent.
- ~~No multi-tenant accounts or authentication in the initial release.~~
  **Also superseded**, and earlier than the line above it: Google sign-in
  through Better Auth landed 2026-09-01 (CLAUDE.md §13), and builder documents
  are *owned* — `service/builder_api.py` scopes every read and write through
  `owner_of(user)`. Multi-tenancy is not what shipped; single-provider
  authentication with per-user ownership is. Recorded here because a reader
  checking "is this authenticated?" against this list would get the wrong
  answer.
- No cross-run agent memory or RAG chat.
- No mobile-first graph layout.
- No synchronous long-running HTTP execution route.
- No batch idea validation until the single-run Flow is stable.
- No indexing of generated scopes, verdicts, or reports as evidence.
- No direct OpenAI model or embedding calls.

## Deferred Enhancements

- Postgres-backed run-history browser.
- Comparison against a hierarchical-manager variant when a real non-deterministic routing need appears.
- Multi-idea batch validation.
- A/B testing the reporter on the OpenRouter cheap tier.
- A/B testing the scoper using operator revision rate as the quality measure.
