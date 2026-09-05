# `40a9c597-0613-4a4f-9ce1-3d9252410445` — the first PRODUCTION run to reach Langfuse

Verified **2026-09-05 (UTC)** by PROD-API, read-only. Nothing here launched a
run, wrote to the application, or spent money: every call was a `GET` against
Langfuse's public API, OpenRouter's `generation` endpoint, or the deployed API's
unauthenticated `/readyz`.

This is the first run **the owner** launched from the deployed studio after the
exporter was turned on an hour earlier (`../../deploy/README.md`). It is not a
proof run: `userId` is a Better Auth user id, not `proof-runner`, and the
studio's own Launch button is what started it.

## 1. Identification

`GET /api/public/traces?environment=live&fromTimestamp=<now-3h>` returned
**exactly one** trace (`meta.totalItems: 1`). There was no ambiguity to resolve
and nothing was guessed.

| | |
| --- | --- |
| app run id (= `sessionId`) | `40a9c597-0613-4a4f-9ce1-3d9252410445` |
| Langfuse trace id | `40a9c59706134a4f9ce13d9252410445` |
| session URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/40a9c597-0613-4a4f-9ce1-3d9252410445` |
| trace URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/40a9c59706134a4f9ce13d9252410445` |
| trace `name` | `idea-validator` |
| `userId` | `gkHdcQ0SRsnaVDWkCXD24AVvJ5vaFVVL` — a Better Auth user id (the owner), **not** `proof-runner` |
| `environment` | `live` |
| `tags` | `['gates:auto', 'idea-validator', 'mode:run']` |
| `release` | `7f8189d12ab9ede10a8825254d0455bfce5d187d` — identical to local `main` HEAD |
| trace `timestamp` | `2026-09-05T22:33:07.966Z` |
| `run` span | `22:33:07.966Z → 22:33:57.901Z`, **49.935 s**, level `DEFAULT`, `parentObservationId: null` |
| terminal | `output.status: completed`, `reason: null`, `error_class: null` — **not** still running |
| app session id | `cc0ecd32-6916-4a66-b63e-54d4bb6717b4` |
| graph version | `9c6ca8a6fefbfffd` |
| verdict (`metadata.computed_result`) | `REJECT`, composite **3.8**, confidence **0.42**, `decision_reason: FLOOR_NO_MARKET`, provisional, D2/M0/C2/F3/X3 |

**It ran in `auto` gate mode, not human.** The brief expected a human-gated
launch; the trace says otherwise, and so does the trace `input`
(`input_keys: ["idea", "no_gates"]`). The console defaults `gatesMode` to
`'auto'` and an **authenticated** caller is allowed it without
`VALIDATOR_ALLOW_AUTO_GATES` (`create_run`), so this is the expected shape for
a signed-in owner who did not press Review. Consequence for the gate check
below: **there is no gate timeline to describe** — zero `gate:*` EVENT
observations, no pause, and the run reached a terminal status on its own.

## 2. What was pulled, and the two pulls

```powershell
$RUN = "40a9c597-0613-4a4f-9ce1-3d9252410445"
$DIR = "docs/observability/evidence/production/$RUN"
.\.venv\Scripts\python.exe scripts\observability\pull_langfuse_run.py --run-id $RUN --out $DIR `
    --poll-stable-seconds 20 --since 2026-09-05T22:33:57Z
.\.venv\Scripts\python.exe scripts\observability\pull_openrouter.py `
    --response-ids-from "$DIR/langfuse-figures.json" --out $DIR
```

**The first pull was short, and it said it was complete.** Run at ~22:37Z it
read **81 observations / 6 generations / 47,709 tokens / $0.071057** and stopped
with `why the wait ended: every generation was billed - nothing left to change`.
That was wrong, and the artifacts are kept as `*-FIRST-PULL.*` rather than
overwritten. A direct `GET /api/public/observations?traceId=…` immediately
afterwards answered `meta.totalItems: 87` and, with `type=GENERATION`,
**12** — so half the generations had not yet arrived. Diagnosis is discrepancy
**D2** below. The second pull (22:41Z) read 87/12, and a **third** independent
read minutes later answered 87/12 again, which is what makes the figures below
settled rather than merely most-recent.

**The Render logs settle when the trace was finished, and the two agree.** The
exporter's own per-run summary line (`TRACE-CONTRACT.md` §10) was emitted at
**22:37:45Z**:

```text
langfuse-exporter run=40a9c597-0613-4a4f-9ce1-3d9252410445 frames_enqueued=181
frames_dropped=0 observations_sent=104 http_errors=0 lookup_ok=12 lookup_failed=0
```

The first pull is timestamped **22:36:58Z** — *before* that line, while six
generations were still being held for their price. The second pull is after it.
`lookup_ok=12 lookup_failed=0` is the exporter saying every billed-cost
resolution succeeded, and `frames_dropped=0 http_errors=0` that it lost nothing
and was refused nothing: an independent confirmation, from the server side, of
the 12 the API now serves. **The summary line is the signal a trace is
complete**, and it is the signal the poller does not have — see D2.
(`frames_enqueued=181` against the app's `frames.captured` of 180 is the
post-terminal `run_completed` metrics frame, which is enqueued after the
snapshot that counts itself; `observations_sent=104` exceeds the 87
observations because an observation is written more than once — opened, ended,
then rewritten by the billed-cost lookup.)

**The app column is the trace's own snapshot, not a `pull_app_run.py` pull.**
The deployed API refuses an anonymous caller — measured, saved in
`app-side-probe.json`:

```text
GET /readyz                     -> 200  observability: exporter enabled, environment live,
                                        capture_content false, resolve_billed_cost true
GET /api/runs/{run_id}          -> 401  {"detail":"sign in to use this endpoint"}
GET /api/runs/{run_id}/frames   -> 401  {"detail":"sign in to use this endpoint"}
```

So `reconcile.py` could not be run: `--app` is required and it exits 2 without
an `app-figures.json`, and its README documents no app-less mode
(`--no-network` removes only E1(c)'s query). **The three-way table below was
therefore written by hand** from the pulled JSON — `three-way-join.md` carries
the per-call join and the command that produced it — and the app column is
`trace.metadata.run_metrics` (`source: app-snapshot`, `reason: run_completed`),
which is the app's own final figure copied into the trace.

## 3. Reconciliation

### Totals — three sides, and the tokens are identical

| metric | app (`run_metrics`, app-snapshot) | Langfuse (12 GENERATIONs) | OpenRouter (12 records) | verdict |
| --- | ---: | ---: | ---: | --- |
| calls | 12 | 12 | 12 | **PASS** |
| input tokens | 48,908 | 48,908 | 48,908 (native) | **PASS** |
| output tokens | 14,124 | 14,124 | 14,124 (native) | **PASS** |
| total tokens | 63,032 | 63,032 | 63,032 (native) | **PASS** |
| cost | $0.07775795 (estimate) | $0.08794491 (billed) | $0.08794491 (billed) | **DIFFERS — D1** |
| LLM time | 42,454 ms (`elapsed_ms`) | 42,302 ms (Σ generation spans) | — | 152 ms apart, 0.36 % |
| generation ids | — | 12 present, 0 missing | 12 found, 0 `not_found` | **PASS** |
| `cost_source` | — | `openrouter-billed` ×12 | — | **PASS** |
| lookups | — | 12 billed / 0 on estimate | — | **PASS** |

OpenRouter's *normalised* counts (44,871 / 11,705) are deliberately not
compared: only the native ones are like-for-like with what the provider
reported to the app.

### Per generation

`three-way-join.md` is the full table. Two facts out of it:

* **`costDetails.total` vs OpenRouter `total_cost`: 0 of 12 differ.** The
  exporter's deferred lookup wrote OpenRouter's own figure onto every one.
* **12 distinct `prompt_fingerprint`s, `prompt_fingerprint_basis: messages` on
  all 12.** No call fell back to the identity hash.

### Cost, attributed — D1

The gap is **+13.1 %** and it decomposes exactly, with no residue:

| tier | model | calls | `service_tier` | billed ÷ `compute_cost_usd` |
| --- | --- | ---: | --- | ---: |
| escalation | `google/gemini-3.8-flash` | 5 | `default` | **1.000** on every call, to the cent |
| cheap | `google/gemini-3.5-flash-lite:nitro` | 7 | **`priority`** | **1.800** on every call, to four decimals |

`compute_cost_usd` prices at the published floor ($0.30 / $2.50 for the lite
model) and its docstring says the billed total can differ. `:nitro` routes on
speed, and every cheap-tier call in this run was served by the **priority**
endpoint at $0.54 / $4.50 — exactly 1.8×. `config.NITRO_PRICE_FACTOR` is
**1.8** and is applied only in `builder/budget.py`; the runtime estimate does
not apply it. So this run is the first **runtime measurement** of the spread
`CLAUDE.md`'s OpenRouter section predicted from the endpoint list, and it landed
on the documented worst case exactly.

One call (`gen-1788647590…`, the scoper) was served by provider **`Google`**
rather than `Google AI Studio`; it is escalation tier and billed at the floor,
so it contributes nothing to the gap. No `cache_discount`, no BYOK, zero
`upstream_inference_cost`, zero reasoning and zero cached tokens on all 12 — so
none of `RECONCILIATION.md` §7A's other candidate causes is in play here.

### E1 — nothing reached Langfuse twice

| check | result |
| --- | --- |
| **2a** GENERATIONs vs app call attempts | 12 vs 12 — **PASS** (no duplicate, no shortfall). The app's 12 is `run_metrics.usage.call_count`, one per TOKEN frame; a frames pull was not available, so the ok/failed split is not separable |
| **2b** a generation id on two observations | **0 — PASS** |
| **2c** a second, OpenRouter-written trace in the window | **0 — PASS.** Done by hand (`e1c-window-traces.json`): `22:23:07Z → 22:43:57Z` (±10 min) returned `totalItems: 1`, this run's own trace, and no trace carrying `metadata["openrouter.api_key_name"]` |

## 4. Contract check (`TRACE-CONTRACT.md`)

| § | requirement | result |
| --- | --- | --- |
| 1 | `sessionId` == app `run_id` | **YES**, byte for byte; the session's own `id` matches too |
| 1 | trace id derived from the run id | `40a9c597-0613-4a4f-9ce1-3d9252410445` → `40a9c59706134a4f9ce13d9252410445` — **YES** |
| 1 | `name` = workflow id / `userId` / `environment` / `tags` | `idea-validator` / the owner's Better Auth id / `live` / `['gates:auto','idea-validator','mode:run']` — **all four correct** |
| 1 | `metadata` carries `run_metrics`, `computed_result`, `unhandled_event_counts` | **all present.** `unhandled_event_counts`: `hook_dispatched 29, agent_logs_started 9, default_env 1, flow_created 1` (C3) |
| 1 | `input` is keys/chars/fingerprint, not content | **YES** — `{input_keys:[idea,no_gates], input_chars:73, input_fingerprint:…}` |
| 2 | hierarchy drawn: run → node → task → agent → generation/tool/event | **YES** — `hierarchy.txt`, one parentless root (`SPAN/run`), 11 node spans, 6 task spans, 6 AGENT, 12 GENERATION, 3 TOOL, 48 EVENT. No ORPHANED subtree, nothing `NOT DRAWN` |
| 3 | seven keys on every observation, nulls named in `null_fields` (Amendment A1) | **YES.** `run_id`/`node_id`/`frame_seq`/`frame_ts`/`frame_kind`/`event_type`/`null_fields` on **87 of 87**. `agent_role` absent on 66 and named in `null_fields` on exactly 66; `task_name` absent on 60 and named on exactly 60. Zero unexplained absences |
| 4 | `usageDetails`, `costDetails.total`, `cost_source`, `response_id`, `provider` | present on **12 of 12**; `usageDetails` keys `{cached,input,output,reasoning,total}` |
| 4 | `prompt_fingerprint_basis` | `messages` on **12 of 12**, 12 distinct fingerprints |
| 4 | error observations carry `level`/`statusMessage`/`error_class` | **3 ERROR observations**, all one event: the reporting task's guardrail. `level: ERROR` and `statusMessage` present on all three; **`error_class` is `null` on all three** — see D3 |
| 5 | TOOL name/input/output/status under the default policy | **YES** — 3 tools, `arg_keys`+`arg_chars`+`arg_fingerprint` in, `output_chars`+`output_fingerprint` out, `tool_status: ok`, `result_count` 3 / 5 / 3, `query` as `{chars, sha256}` |
| 6 | terminal handling; nothing left open | `completed`; the run span ends at `22:33:57.901Z`. **`open-spans.txt`: unfinished spans (non-EVENT, `endTime` null) = 0** of 87 examined; the 48 nulls are all EVENTs, which have no `endTime` by construction |
| 7 | scores | **17** — `run_succeeded` 1 and `run_status` `completed` on the trace, `task_attempts` on all six task spans (1+3+2+2+1+3 = **12**, equal to the generation count), and **9 `guardrail_passed`** (3 zeros on `reporting_task`, one zero on `market_task`, five ones) |
| 8 | content policy, capture off | **YES.** `/readyz` says `capture_content: false`; `input` and `output` are `null` on **all 12** generations; tool text is fingerprinted; even `computed_result`'s free-text fields (`confidence_band`, `fatal_floors`) arrive as `{chars, sha256}` |
| 10 | one exporter summary line per run, with counters | **YES**, 22:37:45Z: `frames_enqueued=181 frames_dropped=0 observations_sent=104 http_errors=0 lookup_ok=12 lookup_failed=0`. `lookup_ok` equals the call count; nothing dropped, nothing refused |

**Gates:** none. `gates:auto`, no `gate:*` observation, no pause, terminal
`completed`.

**Frames:** the app captured **180** frames with `dropped 0, gaps 0,
emit_errors 0, unattributed 0`; observations carry `frame_seq` **1 … 177**. The
three above 177 are the post-terminal verdict/metrics snapshots, which update
trace metadata rather than becoming observations — which is why `run_metrics`
reads `reason: run_completed` at all.

**Per-node spans**, for a reader who wants the shape without opening
`hierarchy.txt`: `scope_idea` 7.157 s → `confirm_scope` / `route_scope` (0 s,
auto-answered) → the three research branches genuinely concurrent
(`research_market` 15.561 s, `research_sentiment` 9.020 s,
`research_feasibility` 9.011 s, all three starting within 12 ms of each other)
→ `synthesize` 3.673 s → `review_verdict` / `route_verdict` → `write_report`
22.691 s → `persist` 0.003 s.

## 5. Discrepancies

**D1 — the app's cost estimate is 13.1 % below the bill.** $0.07775795 against
$0.08794491. **Cause, measured and complete:** all seven `:nitro` cheap-tier
calls were served at `service_tier: priority`, billed at exactly **1.800×** the
published floor the estimator uses; the five escalation calls match to the cent.
Not a defect in the exporter or the tooling — the trace carries the *billed*
figure, which is the only reason the gap is visible at all. It is an argument
for applying `NITRO_PRICE_FACTOR` (already 1.8 in `config.py`) to the runtime
estimate, or for saying on screen that the figure is a floor.

**D2 — `pull_langfuse_run.py` stopped on `all-billed` over an incomplete trace,
and reported it as settled.** The first pull read 6 of 12 generations and half
the money, with `stable: true`. **Cause:** the `all-billed` stop condition is
evaluated over the generations *currently visible*, and it cannot tell "every
generation is billed" from "every generation that has arrived so far is billed".
The exporter holds a generation while its deferred billed-cost lookup retries
(20 / 60 / 180 s), so generations arrive **staggered by lookup-completion
order** — here the last six landed roughly four minutes after the run's terminal
frame, well after the first six. This is the tooling's own `stopped_because`
matrix being over-trusted, not an exporter fault: all 12 eventually arrived, all
12 billed. **A trace's own `metadata.run_metrics.usage.call_count` is in the
same response and is the missing cross-check** — a poll that compared 6 against
12 would not have stopped. The other signal is the exporter's own summary line
(§2): it is written when the trace closes, and the short pull at 22:36:58Z
predates it by 47 s. A verifier with server logs should wait for that line; a
verifier without them — which is anyone pulling a run they did not host — has
only `call_count`. Recorded for whoever owns `scripts/observability/`; nothing
here was changed to work around it, and both pulls are kept.

**D3 — `metadata.error_class` is `null` on all three ERROR observations.**
`statusMessage` is right and identical on all three (`Task failed guardrail 0
validation after 2 retries. Last error: REPORT_URL_CLOSURE: remove body URLs
absent from ValidationReport.sources: …`), and the ERROR level is correctly
propagated to the task span, the agent span and the event. **Cause:** a
guardrail rejection is not an exception — the CrewAI frame carries no error
class, and §4 permits `null` in that case ("the class name or null"). So this is
contract-conformant, and it is recorded only because the previous proof pass
fixed "the exception class reaches every error observation" and a reader
comparing the two runs will ask.

**D4 — B4's side-by-side half is missing.** The app-versus-Langfuse duration
table needs app frame spans, and the app side is 401. Langfuse's own durations
are complete (`durations.md`: report writer 22.395 s slowest agent,
`reporting_task` 22.472 s slowest task, `research_market_landscape` 5.454 s
slowest tool). The one app-side timing that *is* in the trace agrees:
`elapsed_ms` 42,454 against Σ generation spans 42,302 — **152 ms over 12 calls**.

**D5 — cosmetic, in the tooling.** `per-agent.md` / `per-task.md` leave the
input and output cells blank on the `run_metrics` row while filling the total.
`run_metrics.usage` spells them `prompt_tokens` / `completion_tokens`; the
comparison row looks for `input` / `output`. Every total it does print is
correct and both files read **YES**.

**Not a discrepancy, recorded because it will be asked:** 12 calls for a
six-agent flow. The extra six are retries and tool round-trips, and the trace
says so — `task_attempts` 3 on `market_task` and 3 on `reporting_task`, three
calls finishing `tool_calls` rather than `stop`, and four `guardrail_passed: 0`
scores. Nothing is duplicated: 12 distinct prompt fingerprints, 12 distinct
OpenRouter generation ids, 0 duplicate ids inside the session and 0 second trace
beside it.

## 6. Verdict

> **The production exporter delivered this run to Langfuse completely.**

Twelve of twelve LLM calls, token for token identical on all three sides
(48,908 / 14,124 / 63,032), every generation carrying OpenRouter's own billed
cost, the full node → task → agent → generation/tool hierarchy under one
parentless `run` span, zero unfinished spans, all seven §3 keys on all 87
observations with every null accounted for by `null_fields`, 17 scores, the
content policy holding (no prompt, no completion, no tool text, no user input),
and no duplicate — inside the session or beside it.

Nothing is missing from the trace. The only figure that differs anywhere is the
app's own **estimate** of what the run cost, and the trace is what makes that
difference measurable rather than invisible: **D1**. The two process findings —
**D2**, a poller that can stop early, and **D4**, a B4 half that needs a
credential this verifier does not hold — are about the tooling and the access,
not about what the exporter delivered.

## 7. Files

| file | what it is |
| --- | --- |
| `langfuse-{session,traces,observations,scores}.json` | the settled pull, 87 observations / 12 generations |
| `langfuse-figures.{json,md}`, `per-agent.md`, `per-task.md`, `durations.md`, `open-spans.txt`, `hierarchy.txt` | `pull_langfuse_run.py`'s derived evidence |
| `*-FIRST-PULL.*` | the short first pull (81 / 6), kept as the evidence for D2 |
| `openrouter-generations.json`, `openrouter-figures.json`, `openrouter.md` | OpenRouter's own record for all 12 ids |
| `three-way-join.md` | the per-call join, written by hand — see section 2 |
| `e1c-window-traces.json` | E1(c): every trace in the ±10 min window |
| `app-side-probe.json` | `/readyz` plus the two 401s that put the app column out of reach |
| `secret-scan.txt` | F3 over this directory |
