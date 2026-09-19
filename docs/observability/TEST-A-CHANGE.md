# Test a change: compare, export, and a model that reads the runs

Plan 21, branch `admin/test-a-change` from `main` = `4ec0c2b`. Commits
`b0a1771` (API), `554c3bb` (UI), `78a6ca3` (API refine), `c530b3e` (UI refine),
`a22d5dc` (`render.yaml`). PR #31. The contract is
[`.agent/plans/21-test-a-change.md`](../../.agent/plans/21-test-a-change.md)
and its rulings R1 to R9; this file is the binding description of what the code
does and is written against the code rather than against the plan.

Committed, like every file under `docs/observability/`, by the `.gitignore`
exception whose own comment gives the reason: a criterion settled by a file
nobody else can see is an assertion by the builder.

## 1. What it is, and the loop it completes

The loop is four steps, and the first three were already live:

1. **Collect.** A run records what happened: frames, node metrics, gates,
   verdicts (plan 17).
2. **Label.** A finished run's owner or an admin says whether it was any good
   (plan 20, [`RUN-LABELS.md`](RUN-LABELS.md)).
3. **Mine.** The console finds recurring patterns across many runs (plan 19,
   [`GOVERNANCE-INSIGHTS.md`](GOVERNANCE-INSIGHTS.md)).
4. **Test a change.** This plan. You changed the workflow, or you moved a step
   to a different model. Did it help?

Four surfaces, on a seventh admin tab labelled **Improve**, all scoped to one
workflow and one time window:

* **Where runs go wrong** (`/improve/hotspots`): five ranked lists over one
  workflow, per agent, per tool, per error class, per gate and per route, plus
  the outcomes they produced. No model call.
* **Compare two versions** (`/improve/compare`): two arms, six measures, `n`
  printed on the arm itself. An arm under `IMPROVE_MIN_COMPARE_RUNS` (5) is
  shown and flagged, never hidden.
* **Export rated runs** (`/export/evalset`): the runs people rated, streamed as
  one redacted NDJSON file whose first line says what is in it.
* **Ask a model to review** (`/improve/digests`): one cheap-tier model call
  over the mined counts, behind one admin press, capped at
  `DIGEST_MAX_COST_USD` ($0.05) and three brakes.

### Why it was not on main already

Step 4 was designed and largely built on the unmerged branch `admin/mining`
(plan 18). Main received only narrow slices of that programme: plan 19's
Insights and plan 20's labels. The branch could not simply be merged, for two
reasons that are worth stating plainly because they decided the shape of this
plan:

* **Export and Compare rest on the branch's whole mining persistence layer.**
  Taking either one meant taking the layer under it, which is most of the
  branch.
* **The branch's rating code conflicted with main's, and main's is better.**
  Six add/add conflicts, every one of them rating code. Plan 20 shipped a
  rating with a deterministic Langfuse score id, a clear, a note and two doors;
  the branch's predated all of that.

So plan 21 hand-ported the step-4 slice and **dropped** the branch's rating
code entirely (R1). Anything that rates in this repository calls plan 20's
`service/rating_api.py`. Also dropped, and named in section 8: the branch's
deterministic `lessons` rules, its `/improve/lessons` route and its builder
Lessons tab.

## 2. The routes

Five operations, all under `/api/admin`, all
`Depends(require_admin)`, all read-only except the `POST`:

| Operation | Query | What it answers |
| --- | --- | --- |
| `GET /api/admin/improve/hotspots` | `workflow_id` (required), `document_version`, `from`, `to` | Five ranked lists and the outcomes, for one workflow |
| `GET /api/admin/improve/compare` | `workflow_id` (required), `axis=version\|model`, `a`, `b`, `node_id`, `from`, `to` | Two arms, six measures each |
| `GET /api/admin/improve/digests` | `workflow_id` (required), `limit` (1 to 100, default 20) | Stored reviews, the running total, the bounds and whether the knob is on. **Spends nothing and calls no model.** |
| `POST /api/admin/improve/digests` | `workflow_id` (required), `from`, `to` | Writes one review. The only thing here that spends money. |
| `GET /api/admin/export/evalset` | `workflow_id` (required), `rating=good\|bad\|unsure\|any` (default `good`), `from`, `to` | A streamed NDJSON eval file |

Measured on 2026-09-19 off `app.openapi()["paths"]` on this branch: the console
now serves **22 operations over 21 paths** under `/api/admin`, of which
**21 are behind `require_admin`**. `GET /whoami` is the one documented
exception. Operations rather than paths, because `/improve/digests` is one path
and two verbs. Count them off the schema, never off this sentence.

### Every refusal, verbatim

`require_admin` raises FastAPI's own unknown-route body byte for byte, so to a
non-admin every route above is **404 `Not Found`**, indistinguishable from a
path that does not exist. The rest:

| Status | Where | Detail |
| ---: | --- | --- |
| 503 | any route, no durable store | `this service has no durable store, so there is nothing to read` |
| 422 | any route, bad `from`/`to` | the window parser's own sentence |
| 422 | compare | ``axis must be `version` or `model` `` |
| 422 | compare, model axis | `axis=model needs a node_id: two models compared across a whole run measure which node happened to run on which tier, not the models` |
| 422 | export | ``rating must be `good`, `bad`, `unsure` or `any` `` |
| 422 | `POST` digests, knob off | `the model review is off on this deployment; set IMPROVE_DIGEST_ENABLED=1 to turn it on` |
| 429 | `POST` digests, day limit | `this deployment has asked for {n} reviews in the last 24 hours, the limit is {DIGEST_MAX_PER_DAY}; try again after {time}` |
| 429 | `POST` digests, too soon | `a review of this workflow ran less than {DIGEST_MIN_INTERVAL_SECONDS} seconds ago; try again in {n} seconds` |
| 429 | `POST` digests, one in flight | `a review is already running on this deployment; wait for it to finish and try again` |
| 502 | `POST` digests, the model failed | `the model did not answer; the attempt was recorded because it may still have been billed` |

422 rather than 403 for the knob is deliberate: the request is well formed and
the caller is allowed, and what is missing is a deployment setting.

## 3. Compare: six measures, and four special arms

Both axes group the same runs and then measure each group the same way. What
differs is the grouping and, on one measure, the scope.

**The six measures**, with the row labels the panel prints:

| Measure | On screen | Field |
| --- | --- | --- |
| How each run ended | `How they ended` | `status_mix` |
| What they answered, and how sure | `What they answered` | `verdict_mix`, `mean_confidence` |
| What people said afterwards | `What people said` | `rating_mix` (good / bad / unsure / unrated) |
| How often a human sent an approval back | `Approvals sent back` | `gate_revise_rate` |
| How long a run took | `Median time` | `median_duration_ms` |
| What a run cost | `Cost per run` | `cost_per_run_usd` |

No deltas are computed anywhere. The two columns are printed as they are, and
the reader does the subtraction. Every dollar is the app's own estimate off
`run_node_metrics.cost_usd` and carries plan 17's error band.

**The version axis** groups on `runs.document_version`. **The model axis**
groups on `run_node_metrics.model` scoped to one node, and `node_id` is
required (R4): without it a comparison would put a run in which the escalation
tier ran one agent beside a run in which it ran another, and call the
difference a model effect. With it the arms are disjoint, one run to one arm,
and `cost_per_run_usd` is **that node's** cost rather than the whole run's.

**Four arm states, each shown rather than hidden:**

* **`underpowered`** is `n < IMPROVE_MIN_COMPARE_RUNS` (5), and the arm is
  still returned with every measure on it. Hiding it would let a reader
  conclude the comparison could not be made; showing it lets them disbelieve
  it. On screen it appears twice: once above the table, once in the arm's own
  header as `n = {n} · too few runs to tell (needs 5)`.
* **`missing`** is an arm the caller asked for and the window holds no runs of.
  It comes back with `n: 0` and a sentence rather than being omitted, because
  `arms: []` with no explanation is indistinguishable from a broken read.
* **`unknown`** is the arm for a run whose version could not be proved, or
  whose compared node produced no priced call. Never merged into a numbered
  arm: a run whose lineage is unknown is not evidence about either side.
* **`mixed`** is the arm for a run whose compared node ran under more than one
  model, because a fallback fired or the node retried on a second tier. Named
  rather than dropped and rather than counted twice: the run is real evidence
  about something, and it is not evidence about either model alone.

A **hand-written** flow (the Idea validator, the brief flow) has no document
and therefore no versions, so the version axis answers one `unknown` arm
holding every run. The panel says so in a sentence and points at the model
axis instead.

## 4. The export, line by line

`GET /api/admin/export/evalset` streams NDJSON. It is the most
privacy-sensitive artifact this repository produces, and it carries user
content **by design** (R3): an eval set with the input removed is not an eval
set. It is admin-only, redacted, capped on two axes, and it says so in its own
first line.

**Line 1, the header**, verbatim:

> This file contains USER-TYPED CONTENT: run inputs, gate replies a person
> edited, rating notes and a slice of each run's report. Every string has
> passed this service's redaction, which is KEY-NAME based - it removes a
> field called api_key and it does NOT find a credential somebody pasted into
> an idea. Treat it as personal data.

beside `_header: true`, the workflow id, the rating filter, the resolved
window, `max_runs`, `max_bytes` and `generated_at`.

**One line per run**, carrying: `run_id`, `workflow_id`, `document_version`,
`graph_version`, `created_at`, `status`, `mode`, `cost_usd`, `inputs`,
`outcome` (`verdict`, `confidence`, `result_summary` clipped to
`EVALSET_MAX_RESULT_CHARS` = 2,000 characters), `gates` (each answered gate's
id, its approve/revise decision and the field pairs a person edited), `rating`,
`rating_note` and `rated_at`.

**A trailer**, when either cap bit:

* Row cap: `the export stopped at 2000 runs; narrow the window to see the rest`
* Byte cap: `the export stopped at 8388608 bytes; narrow the window or filter by rating to see the rest`

A partial file with a trailer is worth more to whoever is reading it than a
500, which is the call `/api/runs/{id}/logs` already made for frames.

**Caps and redaction:**

| Constant | Value | What it bounds |
| --- | ---: | --- |
| `EVALSET_MAX_RUNS` | 2,000 | rows selected |
| `EVALSET_MAX_BYTES` | 8 MiB | bytes on the wire |
| `EVALSET_MAX_RESULT_CHARS` | 2,000 | characters of each run's report |
| `EVALSET_PAGE_RUNS` | 50 | runs whose payloads are loaded at once |

Every free-text field passes through **both** rules, because they catch
different things: `events/redaction.redact_mapping` removes a field **named**
like a credential, and `observability/content.scrub_text` finds a value
**shaped** like one. Neither finds a credential pasted into an idea under an
innocent name, which is why the header says so in words rather than implying a
guarantee it cannot make.

The paging is the fix for a defect found in review: the route used to build the
payload mapping for every selected run before the first byte, which for 2,000
rows each carrying a 64 KiB result is about 128 MB resident on a response that
called itself streamed. The byte cap bounded the wire and nothing in memory.
The generator now asks for 50 runs at a time, so a download cut off at 8 MiB
never reads the rest.

## 5. Ask a model to review

One `LLM.call` on `CHEAP_MODEL`, with no `Agent`, no `Crew`, no tools and no
memory, so it raises no CrewAI flow events, occupies no admission slot and
appears in no run's frames. Its prompt lives in
`crews/digest_crew/config/tasks.yaml` and `service/digest.py` contains no
prompt literal at all (a test greps for one).

### It never runs unattended

Explicit admin `POST` only: never on page load, never on a `GET`, never on a
schedule. There is no scheduler, no retry and no timer anywhere in
`service/digest.py`.

### The cap, checked twice

`DIGEST_MAX_COST_USD` is **$0.05**. Before anything runs,
`config._assert_digest_cost_ceiling()` prices the two input bounds through the
live price table at the model's dearest measured endpoint; if the worst case
exceeds the cap it **disables the feature** with one ERROR log naming the model
and the figure, rather than raising (R9: a check that made the package
unimportable would take the whole product down over a feature that is off by
default). After the call the **measured** cost is compared with the cap again;
`over_cap` rides both the response and the stored row, and a breach logs at
WARNING. It is decided once, from the cap in force at the moment the tokens
were charged, so a row read back after somebody lowers the cap still says what
was true when it ran.

### The three brakes

| Brake | Constant | Refusal |
| --- | --- | --- |
| One review in flight per process | (a non-blocking lock) | 429 |
| Ten reviews per 24 rolling hours per deployment | `DIGEST_MAX_PER_DAY` = 10 | 429 |
| Thirty seconds between reviews of one workflow | `DIGEST_MIN_INTERVAL_SECONDS` = 30 | 429 |

The day window rolls rather than resetting at midnight, because a calendar
reset hands anybody who waits for it a second full allowance. A **failed**
attempt is stored and counts, because the provider charges for tokens it
generated before it gave up, so a limiter that counted only successes would let
a failing loop spend all day. The arithmetic these bound: ten presses times
five cents is **$0.50 a day at most, per deployment**.

The lock is a measured fix, not a precaution: without it, twenty POSTs produced
twenty model calls and no refusal.

### What the model is sent, and what it is not

`build_sample` passes an **allow-list** of structural keys off each sampled
frame's `details`, and nothing else travels (R2). The list holds names, roles,
kinds, statuses, counts, durations, error classes, the model, retry counts,
`result_count`, `tool_status`, fallback, confidence and the verdict code.
Deliberately absent, and named in the code: `output_preview`, `output_json`,
`query`, `args`, `arguments`, `output`, `text`, `notes`, `feedback`, `inputs`,
`result`, `utterance` and the frame's own `message`.

An allow-list rather than a denylist is the load-bearing choice: a frame kind
that gains a key tomorrow is excluded by default, where a denylist would ship
it to a third party on the day it was added.

Two exceptions, both bounded and scrubbed:

* **An error message**, clipped to `SAMPLE_ERROR_CHARS` (240) and passed
  through `scrub_text`, because an error a person cannot read is an error
  nobody can act on.
* **A node's label**, clipped to `MAX_PROMPT_LABEL_CHARS` (40) and scrubbed,
  because a review that cannot name a node is useless. It is the author's own
  words, and an author can type anything into a node name, including a key.
  The prompt tells the model so in its own rule 4.

The mined counts are scrubbed too: `structural_hotspots` drops
`queries_sample`, because a tool's queries are model-written text and a query
is a tool argument by another name.

The prompt is bounded on three axes, `DIGEST_MAX_SAMPLE_RUNS` (12),
`DIGEST_MAX_SAMPLE_FRAMES` (400) and `DIGEST_MAX_INPUT_CHARS` (40,000), and
the answer on a fourth, `DIGEST_MAX_OUTPUT_TOKENS` (1,200) passed as
`max_tokens`. A prompt that does not fit is truncated in three ordered steps
(drop whole sample runs newest-kept, trim the ranked lists, then clip) and the
stored row records `truncated_sample`, rather than the request being refused at
the moment somebody clicks. That ceiling is now **enforced on the final
rendered string**: it used to shrink the sample only, so a large mined payload
rendered a 51,533-character prompt against a 40,000 ceiling and reported
`truncated: false`, while `worst_case_digest_cost()` priced exactly 40,000.

The output is model output and therefore untrusted: stored as text, rendered
only through the escape-first `markdown.ts`, never re-fed to anything, and read
by no decision this service makes. It is a review for a person.

### It is ON in production, and how to switch it off

`render.yaml` sets `IMPROVE_DIGEST_ENABLED: "1"` (commit `a22d5dc`,
2026-09-19, on the owner's instruction to ship and prove the review). It is a
literal and not a secret: it authenticates nothing, and pressing the button is
what spends, never this value. Set it back to `"0"` to switch the button off.
Note that Render snapshots a deploy's environment when the deploy is
**created**, so the value reaches the running process only on the next deploy
that applies the manifest.

The knob's default in `config.py` is **off**. It is the one environment
variable this plan adds; the scan in `docs/tech-stack.md` section 6 answers
**70** on this branch, measured 2026-09-19.

## 6. Storage

Two additive changes, nothing backfilled, in the same startup migration
(`_ADDITIVE_COLUMNS`) that added `user_id` and the three run-ceiling columns.

**`runs.document_version INTEGER`, nullable.** Stamped at launch from the
published runtime, so every run written from now on records the integer version
of the graph it ran. `create_all()` never alters a table that already shipped,
which is why this goes through the additive migration rather than the table
definition alone; `tests/pg/test_document_version_column.py` proves it on real
PostgreSQL rather than on SQLite.

**`improve_digests`, a new table.** One row per review **attempt**:
`id`, `workflow_id`, `created_by`, `window_from`, `window_to`, `sample_runs`,
`sample_frames`, `truncated_sample`, `model`, `prompt_tokens`,
`completion_tokens`, `cost_usd` (`Numeric(12, 6)`, nullable), `over_cap`,
**`error`**, `body`, `created_at`, plus an index on
`(workflow_id, created_at)`.

`error` is the column that makes the per-day brake honest: it holds a failed
attempt's reason and is NULL for a review that worked, so the limiter counts
what may have been spent rather than what succeeded. A durable row is also the
only record a restart cannot forget, which an in-memory attempt counter would.

`cost_usd` is nullable rather than defaulted to zero, because "no price on
file" and "this call was free" are different facts, and reporting the second
for the first is the defect that once priced a 128,069-token run at $0.00.

One serializer addition, and only one (R6): a task's completion frame now
carries `tool_failure_count` on every completion and up to
`MAX_TASK_TOOL_FAILURES` (8) `{tool, error_class}` rows. Nothing else was
ported, and `output_preview` deliberately was not.

## 7. How to verify

### The modules

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///:memory:"
.\.venv\Scripts\python.exe -m unittest tests.service.test_improve_compare -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_improve_mining -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_improve_config -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_improve_fixture_shapes -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_evalset_export -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_digest -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_document_version_stamp -v
.\.venv\Scripts\python.exe -m unittest tests.service.test_additive_migration -v
.\.venv\Scripts\python.exe -m unittest tests.test_env_knob_doc -v
# needs the pg18-test container, and must NOT skip:
.\.venv\Scripts\python.exe -m unittest tests.pg.test_document_version_column -v
Push-Location frontend; npx vitest run adminImprove adminPanels; Pop-Location
```

**No test in this repository calls a model or the network.** `run_digest` takes
an `llm_factory` and every test passes a fake, so no test can reach OpenRouter
by forgetting a patch. Three guards are worth knowing by name, because each was
written against a defect that had already shipped:

* `test_digest.py::TheLoopIsNotParkedTests::test_every_improve_handler_is_a_sync_def`
  walks the app's routes, filters to `/improve/` and `/export/evalset`, asserts
  none is a coroutine function, and asserts it checked exactly five so it
  cannot pass on zero.
* `test_digest.py::RunDigestTests::test_the_bus_is_left_exactly_as_it_was_found`
  counts handlers on CrewAI's process-wide event bus before and after three
  reviews.
* `test_digest.py::NoContentReachesThePromptTests` plants a credential in a
  tool's arguments, in an output preview and in an error message, and fails if
  any of them reaches the rendered prompt. Its negative control,
  `test_it_fails_when_the_allow_list_is_removed`, widens the allow-list and
  asserts the secret then **does** arrive, so the guard cannot rot into a test
  that passes over nothing.

The UI fixture is generated, never typed:
`.\.venv\Scripts\python.exe scripts\emit_improve_fixture.py --check` fails with
`frontend/tests/fixtures/improveApi.json is stale; re-run
scripts/emit_improve_fixture.py`.

### The free local flywheel, end to end

Run on 2026-09-19 against a `SYNTHETIC=1` backend. It spends nothing.

```powershell
$env:SYNTHETIC = "1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS = "5"; $env:PORT = "8099"
$env:CREDENTIALS_MASTER_KEY = "Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE="
.\.venv\Scripts\serve.exe
```

1. Draw or open a builder workflow and **publish it**. This pass used the
   built-in "minimal gated agent" template, published as **v1**.
2. Launch **five** runs and rate each one. This pass rated 2 good, 2 bad and
   1 not sure. **Launch them one at a time** (see section 9).
3. Edit the workflow and republish as **v2**. This pass moved the agent from
   the cheap tier to escalation and raised `max_iter` from 2 to 3.
4. Launch five more runs and rate them: 4 good, 1 bad.
5. Open `#/admin`, tab **Improve**, choose the workflow.

What it answered:

| Check | Result |
| --- | --- |
| Compare, version axis | two arms, `n = 5` each, cost per run **$0.000324** (v1) against **$0.000643** (v2), neither flagged |
| Compare, model axis on node `draft` | the same ten runs split by model, arms disjoint |
| Compare, model axis with no `node_id` | **422** |
| Any of the five routes as a non-admin | **404** |
| Export, `rating=good` | the header line plus **6** run lines, each carrying its `document_version` |
| Where runs go wrong | five lists rendered |

The version numbers on the arms are the proof that the whole chain works:
publish writes the version, the runtime carries it, `create_run` stamps it, and
the comparison reads it.

### The one real model review

One press against the live model on 2026-09-19, and the only paid thing in this
plan's verification:

* **$0.0015559 measured**, from 1,528 prompt and 439 completion tokens priced
  through `config.compute_cost_usd`, against the **$0.05** cap.
* **4.0 seconds**, `over_cap: false`.
* An immediate second `POST` answered **429**, `a review of this workflow ran
  less than 30 seconds ago`.

That is 3.1% of one press's ceiling, so the $0.05 cap has three decimal orders
of headroom over a real review of a small workflow. It is one measurement of
one workflow and should not be read as a forecast for a large one.

## 8. What is not built

Named here so nobody goes looking, and because the programme this was ported
from exists and is still unmerged.

* **The deterministic `lessons` rules.** Plan 18's fourteen `$0.00` rules,
  `service/lessons.py`, the `/improve/lessons` route and the builder's own
  **Lessons** tab were all dropped by R1 and remain on `admin/mining`. This
  plan's teaching layer is the model review and nothing else.
* **Comparing a hand-written workflow by version.** The Idea validator and the
  brief flow have no document and no versions, so only the model axis applies
  to them. This is a property of what they are, not a gap in the code, and the
  panel says so.
* **No scheduled review.** No cron, no timer, no retry, no page-load fetch. A
  review happens because an admin pressed a button.
* **No automatic change to anything.** The review is prose for a person to
  read. Nothing edits a prompt, a model, a node or a workflow from it, and no
  decision this service makes reads it.
* **No rating code.** Rating is plan 20's, at
  `service/rating_api.py`; this plan reads the word and never writes it.
* **No gate proposal display.** The branch's `AdminDrawer` gate-proposal
  hunks were dropped with the rest.

## 9. Honest limits

* **A version is only stamped on runs launched after this shipped.** Older
  runs have `document_version` NULL, and `resolve_document_version` is the only
  thing that can answer for them: it recomputes each stored version's content
  hash and matches it against `runs.graph_version`. A hash it cannot match, a
  document that no longer parses, a store that will not answer and a history
  longer than `IMPROVE_MAX_VERSION_SCAN` (200) all land in the **`unknown`**
  arm. A version this code cannot prove is not a version it will guess.
* **Five runs per arm is a triage floor, not a significance test.**
  `IMPROVE_MIN_COMPARE_RUNS` is the point below which the panel refuses to let
  a reader forget how thin the evidence is. Above it, nothing here computes a
  p-value, a confidence interval or a power calculation, and a difference over
  six runs is still probably noise.
* **Cost means two different things on the two axes.** On the version axis
  `cost_per_run_usd` is the **whole run's** cost. On the model axis it is the
  **compared node's** cost only, because the whole run's would carry every
  other node's spend into a figure labelled as one model's. Both are the app's
  own estimate off `run_node_metrics`, blind to embeddings, rerank and
  Firecrawl, and both carry plan 17's measured error band.
* **Every scan is bounded and says so.** `truncated` rides every response, and
  a truncated window makes each count a floor rather than a total. Counts are
  not prevalence estimates and must not be compared across workflows.
* **Frame retention deletes the evidence.** With
  `VALIDATOR_RUN_RETENTION_DAYS` set, an old run's frames are gone, so the
  mined lists and the verdict measures thin out behind the window without
  saying which run went missing.
* **A CLI run appears nowhere here.** `validate --idea` and `run_crew` never
  enter the service's capture scope, so they have no run id, no rating and no
  row to compare.
* **The review's cost is its own.** A review has no `run_id`, so it appears in
  no `run_node_metrics` row and in no run's spend. `total_cost_usd` on the
  digests read is the only place this money is visible, and it is never added
  to run spend.
* **The export's redaction is key-name based.** It removes a field called
  `api_key` and it does not find a credential somebody pasted into the text of
  an idea. The header line says so, and nothing downstream can make that
  guarantee stronger.
* **The panel's own numbers are the model's only evidence.** The review reads
  the mined counts and a bounded structural sample. It has never seen a prompt,
  an answer, a tool argument or a person's words, so it cannot tell you why an
  answer was wrong, only where the failures cluster.

## Production proof

Measured on production, 2026-09-19, signed in as the owner, PR #31 live as `e6b0155`.

**The workflow.** A builder workflow made from the minimal gated agent template
(`ug_5c0a614f`): an input, one approval gate, one library agent (the scoper), an output.

**Collect.** Version 1 (agent on the cheap tier) was published and run five times with five
different startup ideas. Each run paused at its gate, the gate was approved, the run completed.
Version 2 (the same agent moved to the dearer tier, nothing else changed) was published and run
on the SAME five ideas, so the two samples are matched. Ten real runs; every one a Langfuse trace
in the `live` environment carrying `gate_outcome: approve`.

**Label.** Every run was rated against one rule taken from the scoper's own task: the community
and repository queries must each be 2 to 4 plain keywords. An honest detour is recorded here
because it is what labelling is like: the first rule used (2 to 4 QUERIES per branch) misread the
task, and rated all ten runs bad. Reading the prompt showed the task asks for exactly ONE query of
2 to 4 KEYWORDS. All ten runs were re-rated under the corrected rule. On the trace, each run still
carries exactly ONE `human_rating` score after being rated two or three times (read back through
Langfuse's API): re-rating replaces, it does not append.

**Mine.** The Improve tab's first section read: "People said something about 10 of 10 runs:
9 good, 1 bad."

**Test a change.** `Compare two versions`, version 1 against version 2, five runs each, neither
side flagged as too few:

| Measure | Version 1 (cheap tier) | Version 2 (dearer tier) |
| --- | --- | --- |
| How they ended | Completed 5 | Completed 5 |
| What people said | Good 4, Bad 1 | Good 5 |
| Approvals sent back | 0% | 0% |
| Cost per run (estimate) | $0.0009 | $0.0067 |

The one bad run on version 1 wrote a five-word repository query. Version 2 wrote three keywords
every time. So the change bought one better run in five for about seven times the cost per run.
Five runs a side is a triage floor, not a significance test, and the reading is the owner's to
make; the tool's job was to put the two columns side by side, and it did. (Median time is not a
fair measure in this sample: version 1's runs sat at their gates while the driving script was
being corrected, 1m 52s against 43s.)

**Export.** `Export rated runs`, rating Good: a header line plus nine runs, five stamped
version 2 and four stamped version 1, each with its input, its approval and its rating.

**Found on production by using it, recorded as follow-ups:** the workflow picker shows a
workflow's id rather than its name; the two version fields are free text rather than a list of
the versions that exist; and Render did not apply `render.yaml`'s `IMPROVE_DIGEST_ENABLED` to the
already-created API service, so the variable had to be added in the dashboard (with the owner's
permission) before the model review could be pressed.

**A model reading the runs.** With the owner's permission `IMPROVE_DIGEST_ENABLED=1` was added to
the API service in the Render dashboard and the service redeployed; the section then read
"Turned on here: yes, 10 of 10 reviews left today". The button was pressed ONCE. The review came
back in a few seconds: **$0.0022 of the $0.05 ceiling**, 10 runs read, 80 frames, 5,028 tokens in
and 278 out, and the section then read "Reviews so far: 1, $0.0022 spent" and "9 of 10 reviews left
today". Every sentence of the review cites a count ("Out of 10 rated runs, 9 received a good
rating"), and where a count is small it says so ("Because this count rests on fewer than five
runs, this is a small sample hint"). A free local review earlier the same day measured $0.0016.

