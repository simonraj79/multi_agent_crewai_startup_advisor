# What a person sees in the Langfuse console for one production run

Captured **2026-09-06**, roughly 06:40–06:48 local (UTC+8), from a signed-in
Chrome session against the live Langfuse Cloud project. Read-only: nothing on
this page changed a trace, a score, a comment or a setting, and no code in this
repository was edited to produce it.

**Method.** A real browser, the console's own UI, and the console's own numbers.
Every figure below is quoted from a rendered surface — none is computed from the
API, from the exporter's source, or from a test. Where I did arithmetic over
those figures it says so.

> **Credential hygiene.** The generation and run metadata panels contain a
> `scope.attributes.public_key` row holding the Langfuse ingest key
> (`pk-lf-…`). **Its value is not written anywhere in this directory**, and it
> is not in any screenshot: capture 03 is a *region* capture deliberately cut
> above that row, and every other capture stops before the metadata scrolls that
> far. All nine PNGs were byte-searched for `pk-lf-`, `pk_lf` and `sk-lf-`
> afterwards — **zero hits in all nine**. That byte-check is weak on its own
> (PNG is compressed), which is why the primary control was never framing the
> row.

---

## 1. Which run this is

Sessions list, `Past 1 day`, sorted newest first. Every other live session in
the window belongs to `proof-runner`; the newest one that does not is:

| | |
| --- | --- |
| **Session ID / run id** | `40a9c597-0613-4a4f-9ce1-3d9252410445` |
| **Trace ID** | `40a9c59706134a4f9ce13d9252410445` (the run id with the dashes removed) |
| **Created at** | `2026-09-06 06:33:07` (console local; the trace's own `frame_ts` is `2026-09-05T22:33:07.965Z`, so the console is rendering **UTC+8**) |
| **Duration** | `50.00s` in the sessions list; `49.94s` on the trace |
| **Environment** | `live` |
| **User ID** | `gkHdcQ0SRsnaVDWkCXD24AVvJ5vaFVVL` — a 32-char Better Auth user id, i.e. the owner's Google sign-in, not a probe identity |
| **Traces** | 1 |
| **Session total cost** | the session page reads **`Total cost: $0.00`** — see finding F4 |

Session page: <https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/40a9c597-0613-4a4f-9ce1-3d9252410445>

The session card names the trace **`idea-validator`**. On the trace page the
title reads `run: 40a9c597…` because that page titles itself with the **root
observation** (`run`), not the trace. Both are true; they are different objects.

The trace stamps `Release: 7f8189d12ab9ede10a8825254d0455bfce5d187d`, and local
`git log --oneline -1` at capture time answered
`7f8189d docs(observability): the deploy that turned the exporter on, …`. **The
production run was served by the commit this working tree is sitting on**, so
nothing here is a reading of a stale deploy.

---

## 2. The screenshots

| File | Console URL | What it shows |
| --- | --- | --- |
| `01-sessions-list.png` | [/sessions](https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions) | The sessions table, newest first, with the target row at the top: `40a9c597-…`, `2026-09-06 06:33:07`, `50.00s`, `live`, user `gkHdcQ0SRsnaVDWkCXD24AVvJ5vaFVVL`, 1 trace. Every row beneath it is `proof-runner` or `anonymous`/`synthetic`. |
| `02-trace-tree.png` | [/traces/40a9c597…](https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/40a9c59706134a4f9ce13d9252410445) | Trace header — latency `49.94s`, session, user, `Env: live`, `Release: 7f8189d12ab9ede10a8825254d0455bfce5d187d`, `$0.087945`, `48,908 prompt → 14,124 completion (∑ 63,032)`, tags `idea-validator` / `gates:auto` / `mode:run` — beside the observation tree from `run` down through `scope_idea → scoping_task → Startup validation scoper → google/gemini-3.8-flash`, then `confirm_scope`, `route_scope`, `research_market → market_task → Market evidence analyst → …`. The full run → node → task → agent → tool/generation chain. |
| `02b-trace-tree-scrolled.png` | same | The tail of the tree: `synthesis_task` → `Startup validation synthesist` → its generation; `review_verdict`; `route_verdict`; and **`write_report` → `reporting_task` ERROR → `Validation report writer` ERROR**, carrying `guardrail_passed: 0.00, 0.00, 0.00` and `task_attempts: 3.00`. |
| `03-generation-detail.png` | [?observation=7d4c4d4a8591f95e](https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/40a9c59706134a4f9ce13d9252410445?observation=7d4c4d4a8591f95e) | One generation, the first of the report writer's three. Header: `google/gemini-3.8-flash`, `Latency: 7.85s`, `Env: live`, `$0.016181`, `5,099 prompt → 3,295 completion (∑ 8,394)`. Metadata: `provider "Google AI Studio"`, `openrouter_cost_usd 0.0161805`, `prompt_chars 16968`, `completion_chars 10135`, `message_count 2`, `prompt_fingerprint_basis "messages"`, `observation_role "generation"`, **`cost_source "openrouter-billed"`**, `attempt 1`, `finish_reason "stop"`, `event_type "MODEL_CALL"`, `frame_seq 142`, `task_name "reporting_task"`, `agent_role "Validation report writer"`. **Region capture, cut above the `node_id` / `run_id` / `scope.attributes.public_key` rows.** |
| `04-scores.png` | [?traceTab=scores](https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/40a9c59706134a4f9ce13d9252410445?traceTab=scores) | The trace's Scores table — Timestamp / Name / Value / Comment, `Page 1 of 1`. |
| `05-timeline.png` | [?view=timeline](https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/40a9c59706134a4f9ce13d9252410445?traceTab=scores&view=timeline) | The Gantt view with `Show labels` on: a `49.94s window`, each span's bar, duration and rolled-up cost. |
| `06-observations-filtered.png` | [/traces?filter=traceId…](https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces?filter=traceId%3Bstring%3B%3Bcontains%3B40a9c59706134a4f9ce13d9252410445&searchType=id&searchType=content) | The observations table filtered to this trace: **`Total ≈ 87`**, with the facet panel giving the per-name and per-type breakdown. This is the only place the console will tell you a trace's observation count. |
| `07-run-metrics.png` | trace page, metadata expanded | `run_metrics`: `prompt_tokens 48908`, `completion_tokens 14124`, `total_tokens 63032`, `call_count 12`, `successful_requests 12`, `elapsed_ms 42454`, **`cost_usd 0.07775795`**, `frames { captured 180, dropped 0, gaps 0, emit_errors 0, subscriber_dropped 0, unattributed 0 }`, `source "app-snapshot"`. |
| `08-computed-result.png` | trace page, metadata expanded | `computed_result`: **`verdict "REJECT"`**, `composite_score 3.8`, `confidence 0.42`, `provisional true`, `decision_reason "FLOOR_NO_MARKET"`, `dimensions { demand 2, market 0, competitive_room 2, feasibility 3, headroom_over_free 3 }`, `anchor_margins { D 1, M 1, C 1, F 1, X 1 }`. `confidence_band` and `fatal_floors` render as `{ chars, sha256 }` rather than as values. |

---

## 3. What the tree says

### Header, as the console states it

```
Latency        49.94s
Total cost     $0.087945
Usage          48,908 prompt -> 14,124 completion (sum 63,032)
Environment    live
Release        7f8189d12ab9ede10a8825254d0455bfce5d187d
Tags           idea-validator   gates:auto   mode:run
Session        40a9c597-0613-4a4f-9ce1-3d9252410445
User           gkHdcQ0SRsnaVDWkCXD24AVvJ5vaFVVL
Input          input_chars 73, input_fingerprint a2899d84..., input_keys ["idea","no_gates"]
Output         status "completed", reason null, error_class null
```

Root-observation metadata also carries `synthetic "False"`, `mode "run"`,
`gates "auto"`, `workflow_id "idea-validator"`, `graph_version "9c6ca8a6fefbfffd"`,
`app_session_id "cc0ecd32-6916-4a66-b63e-54d4bb6717b4"`.

### Observation count and shape

From the filtered observations table (`06`), for this trace only:

| Type | Count |
| --- | ---: |
| EVENT | 48 |
| SPAN | 18 |
| GENERATION | 12 |
| AGENT | 6 |
| TOOL | 3 |
| **Total** | **87** |

`Is Root Observation: True 1 / False 86`. `Environment: live 87`.
By name: `AGENT_CALL` 48, `google/gemini-3.5-flash-lite:nitro` 7,
`google/gemini-3.8-flash` 5, then one each of the six agents, the three tools,
`confirm_scope`, and the rest of the node spans.

### The six agents, and where the money went

The tree names every agent by its CrewAI role string. Node-level rolled-up cost:

| Node | Task | Agent | Duration | Cost | Share |
| --- | --- | --- | ---: | ---: | ---: |
| `scope_idea` | `scoping_task` | Startup validation scoper | 7.16s | $0.004199 | 4.8% |
| `research_market` | `market_task` | Market evidence analyst | 15.56s | $0.011802 | 13.4% |
| `research_sentiment` | `sentiment_task` | Community demand analyst | 9.02s | $0.006415 | 7.3% |
| `research_feasibility` | `feasibility_task` | Technical feasibility analyst | 9.01s | $0.004704 | 5.3% |
| `synthesize` | `synthesis_task` | Startup validation synthesist | 3.67s | $0.008649 | 9.8% |
| **`write_report`** | **`reporting_task` — ERROR** | **Validation report writer — ERROR** | **22.69s** | **$0.052177** | **59.3%** |

Plus zero-cost spans `confirm_scope` (−0.00s), `route_scope`, `review_verdict`
(0.00s), `route_verdict` (0.00s), `persist` (0.00s), and three tool spans:
`research_market_landscape` (5.45s), `analyze_community_sentiment` (4.33s),
`assess_technical_feasibility` (3.26s).

### The twelve generations

| # | Node | Under | Model | Latency | Tokens | Cost |
| --: | --- | --- | --- | ---: | --- | ---: |
| 1 | `scope_idea` | Startup validation scoper | `google/gemini-3.8-flash` | 6.88s | 1,673 -> 785 (2,458) | $0.004199 |
| 2 | `research_market` | Market evidence analyst | `gemini-3.5-flash-lite:nitro` | 0.69s | 2,650 -> 31 (2,681) | $0.001571 |
| 3 | `research_market` | `research_market_landscape` | `gemini-3.5-flash-lite:nitro` | 2.10s | 3,270 -> 715 (3,985) | $0.004983 |
| 4 | `research_market` | `research_market_landscape` | `gemini-3.5-flash-lite:nitro` | 2.07s | 3,719 -> 720 (4,439) | $0.005248 |
| 5 | `research_sentiment` | Community demand analyst | `gemini-3.5-flash-lite:nitro` | 0.79s | 1,935 -> 36 (1,971) | $0.001207 |
| 6 | `research_sentiment` | `analyze_community_sentiment` | `gemini-3.5-flash-lite:nitro` | 2.04s | 2,819 -> 819 (3,638) | $0.005208 |
| 7 | `research_feasibility` | Technical feasibility analyst | `gemini-3.5-flash-lite:nitro` | 0.66s | 1,697 -> 26 (1,723) | $0.001033 |
| 8 | `research_feasibility` | `assess_technical_feasibility` | `gemini-3.5-flash-lite:nitro` | 1.56s | 2,314 -> 538 (2,852) | $0.003671 |
| 9 | `synthesize` | Startup validation synthesist | `google/gemini-3.8-flash` | 3.40s | 7,347 -> 837 (8,184) | $0.008649 |
| 10 | `write_report` | Validation report writer | `google/gemini-3.8-flash` | 7.85s | 5,099 -> 3,295 (8,394) | $0.016181 |
| 11 | `write_report` | Validation report writer | `google/gemini-3.8-flash` | 7.31s | 8,197 -> 3,309 (11,506) | $0.018557 |
| 12 | `write_report` | Validation report writer | `google/gemini-3.8-flash` | 6.96s | 8,188 -> 3,013 (11,201) | $0.017440 |

*My arithmetic over the console's own figures, as a consistency check:* the
twelve prompt counts sum to **48,908** and the twelve completion counts to
**14,124** — exactly the header's totals; the twelve costs sum to
**$0.087947**, against the header's **$0.087945**. Nothing is missing and
nothing is double-counted.

Only two models appear. `google/gemini-3.5-flash-lite:nitro` is the cheap tier
(7 calls, the three research branches); `google/gemini-3.8-flash` is escalation
(5 calls: scoper, synthesist, and the report writer's three).

### ERROR observations

Three of the 87 are not `level:DEFAULT` (the search facet reads
`level:DEFAULT 84` of 87), and all three are the same failure:

1. `reporting_task` — **ERROR**, 22.47s, `guardrail_passed: 0.00, 0.00, 0.00`, `task_attempts: 3.00`
2. `Validation report writer` — **ERROR**, 22.39s
3. one `AGENT_CALL` event under `write_report` — **ERROR**

### Gate events

**There are none, and that is the correct behaviour for this run.** The trace is
tagged `gates:auto`, its metadata says `gates "auto"`, and its input keys are
`["idea", "no_gates"]` — this run was launched **unattended** from the studio by
an authenticated user, not with human gates. The two gate nodes exist as spans
and took no time: `confirm_scope` (−0.00s) and `review_verdict` (0.00s). There
is no `gate:confirm_scope` open/answered pair to find.

### Is the run finished?

**Yes, and it succeeded by its own report.** The root `run` span is closed at
49.94s, its output is `status "completed"`, the trace-level scores are
`run_status: completed` and `run_succeeded: 1`, and `run_metrics.reason` is
`"run_completed"`. It is not paused at a gate and not still running.

---

## 4. Scores

The Scores tab lists **17 scores, one page**, across four names:

| Name | Level | Count | Values (newest to oldest) |
| --- | --- | ---: | --- |
| `run_status` | Trace | 1 | `completed` (06:33:57) |
| `run_succeeded` | Trace | 1 | `1` (06:33:57) |
| `guardrail_passed` | Observation | 9 | `0, 0, 0, 1, 1, 0, 1, 1, 1` |
| `task_attempts` | Observation | 6 | `3, 1, 3, 2, 2, 1` |

Timestamps run `06:33:15` to `06:33:57`. Six `task_attempts` scores for six
tasks; nine `guardrail_passed` because a retried task scores once per attempt —
`reporting_task` contributes `0, 0, 0` and `market_task` contributes `1, 0`.

---

## 5. Timeline

`05-timeline.png`, `Show labels` on, `49.94s window`. Each row carries its
duration and rolled-up cost, so the shape of the run is legible at a glance:
`scope_idea` first, then the three research branches, then `synthesize`, then a
long `write_report` tail.

**The fan-out is genuinely parallel, and the timeline shows it.** All three
research bars start at roughly the same offset (~6s) and overlap. The
arithmetic agrees: serial branches would need
7.16 + 15.56 + 9.02 + 9.01 + 3.67 + 22.69 = **67.11s**, but the run took
**49.94s**; with the branches concurrent the prediction is
7.16 + max(15.56, 9.02, 9.01) + 3.67 + 22.69 = **49.08s**, which is the measured
figure to within a second of gate and router overhead.

---

## 6. The verdict the run produced, readable from the console

Nothing in this trace carries a prompt or a completion — but the *decision* is
right there in the root observation's metadata:

```
verdict           REJECT
composite_score   3.8
confidence        0.42
provisional       true
decision_reason   FLOOR_NO_MARKET
dimensions        demand 2, market 0, competitive_room 2, feasibility 3, headroom_over_free 3
anchor_margins    D 1, M 1, C 1, F 1, X 1
```

`market 0` and `decision_reason FLOOR_NO_MARKET` agree with each other, so the
verdict is self-consistent on its face.

`confidence_band` and `fatal_floors` are not values but `{ chars, sha256 }`
pairs — the exporter redacts those two strings to a length and a digest.
`fatal_floors[0].chars` is **15**, and `FLOOR_NO_MARKET` is exactly 15
characters, so a reader can infer the floor from the length even though the
string was withheld. Whether that is acceptable redaction or an accidental
oracle is a design question, not a defect I can settle from the console.

---

## 7. Findings

**F1 — The trace was still being backfilled while I read it, and the totals
moved.** My first read of the trace header said **`$0.071057`** and
**`35,820 -> 11,889 (47,709)`** over **9** generations, with `scope_idea`,
`research_sentiment` and `research_feasibility` showing *no* generation and *no*
cost at all. Ten seconds and a reload later the same page said **`$0.087945`**
and **`48,908 -> 14,124 (63,032)`** over **12** generations, and the three
"missing" branches had their generations. The second reading held across two
further reloads and is the one reported above.

This matters twice over. It is **not** a gap in instrumentation — the earlier
reading was flush lag, and anyone who screenshots a fresh trace will capture a
number that is wrong by 24% in cost and by three whole LLM calls. And the
console warns about a related lag in its own banner on the Tracing page:
*"New data in ~15 min. Upgrade your instrumentation for real-time data."*
**A production run should be read some minutes after it ends, not while it is
landing.**

**F2 — The report writer failed three times, and the run still reports success.**
`reporting_task` is `ERROR` with `guardrail_passed: 0.00, 0.00, 0.00` over
`task_attempts: 3.00`; `Validation report writer` is `ERROR`; one `AGENT_CALL`
under it is `ERROR`. Against that, the trace output is `status "completed"`,
`run_status: completed`, `run_succeeded: 1`, and `error_class: null`. Both are
faithful to their own layer — the flow completed, the reporting task's guardrail
never passed — but a person scanning the sessions list, or a dashboard keyed on
`run_succeeded`, sees an unqualified success over a run whose most expensive
node exhausted its retries. **This is the single most useful thing the console
shows about this run and the least visible.**

**F3 — The failed node is 59% of the bill.** `write_report` cost `$0.052177` of
`$0.087945` across three escalation-tier calls of ~8k, ~11.5k and ~11.2k tokens.
The three guardrail failures are not cheap retries; they are the majority of the
run's spend. `market_task` shows the same pattern in miniature —
`guardrail_passed: 1.00, 0.00`, `task_attempts: 3.00`.

**F4 — The session page reads `Total cost: $0.00` for a $0.088 run.** The trace
inside it reports `$0.087945` correctly. Someone triaging from
`/sessions` — the natural entry point, and the surface this task starts from —
would conclude the run was free. Worth checking whether this is a Langfuse
session-rollup lag (it is the same aggregate that the "~15 min" banner governs)
or a stable mis-rollup; one session is not enough to tell.

**F5 — Two independent cost numbers disagree by 13%, and the console shows both.**
The trace header's `$0.087945` is the sum of the twelve generations'
`openrouter_cost_usd`, each stamped `cost_source: "openrouter-billed"` — real
billed cost, not an estimate. The app's own `run_metrics.cost_usd` in the same
panel says **`0.07775795`**, `source: "app-snapshot"`. The gap is `$0.0102`,
11.6% of the billed figure. `run_metrics.elapsed_ms` (42,454) is likewise 7.5s
short of the trace's 49.94s latency. Both look like the app snapshotting itself
before the last calls settled — the same flush-order effect as F1, recorded
durably this time. **`cost_source` is the answer to the question this task
asked: for this run it is `openrouter-billed` throughout, so the Langfuse
figure is the trustworthy one and the app's own is the one that lags.**

**F6 — No prompts or completions are in the trace, by construction.** Every
generation's `Input` is `null` and `Output` is `undefined`; the trace object
itself carries neither, and Langfuse renders its own hint: *"Looks like this
trace didn't receive an input or output."* What is exported instead is
`prompt_chars`, `completion_chars`, `message_count`, `prompt_fingerprint` and
`prompt_fingerprint_basis: "messages"` — shape and identity, never content.
That is a coherent privacy posture and it should be recorded as a deliberate
choice, because it also means **the console cannot tell you *why* the report
guardrail failed** — only that it did, three times, for five cents.

**F7 — `unhandled_event_counts` is non-zero: `hook_dispatched 29`,
`agent_logs_started 9`, `default_env 1`, `flow_created 1`** — 40 events the
exporter saw and did not map to a span. Against that, `frames` reports
`captured 180, dropped 0, gaps 0, emit_errors 0, subscriber_dropped 0,
unattributed 0`. So nothing was lost or misattributed; 40 events were
deliberately not modelled. Whether `hook_dispatched` at 29 deserves a span is a
call for whoever owns the exporter.

**F8 — 48 of the 87 observations are `AGENT_CALL` events carrying nothing.**
They render as `0ms` rows in the timeline and as untyped leaves in the tree,
and they are 55% of the trace's observations. They make the tree noticeably
harder to read — the run → node → task → agent → generation spine is real and
clear, but it is interleaved with four or five `AGENT_CALL` rows at every level.

**F9 — The ingest public key is in every observation's metadata.** Langfuse
itself writes `scope.attributes.public_key` into the rendered metadata of the
root span and of every generation. It is a *public* (ingest) key rather than a
secret, and it is Langfuse's own doing rather than this exporter's — but it
means **any casual screenshot of a metadata panel leaks it**, and it sits three
rows below `agent_role`/`task_name`, which are exactly the rows somebody would
screenshot. That is why capture `03` here is a region capture.

---

## 8. Verdict — what a person can actually read from the console

**They can read a great deal, and the one thing they would most want to know is
the one thing they will miss.**

Within about a minute on the trace page, without touching the API, a person can
establish: this was a real (`synthetic "False"`), authenticated, unattended
(`gates:auto`) production run of `idea-validator` at release `7f8189d1`; it took
**49.94s**, made **12 model calls** on exactly two models, burned **63,032
tokens** and cost **$0.087945** billed by OpenRouter; its three research
branches genuinely ran in parallel; and it concluded **REJECT, composite 3.8,
confidence 0.42, provisional, on `FLOOR_NO_MARKET`**. Every agent is named by
its real CrewAI role, every generation is attributed to the right agent, task
and node, and the cost lands on the node that spent it. The instrumentation is
doing its job.

- **Which agent cost most:** the **Validation report writer**, `$0.052177` —
  **59.3%** of the run — over three `gemini-3.8-flash` calls. The whole
  three-branch research fan-out together cost `$0.022921`, less than half of it.
- **Did anything fail:** **yes.** `reporting_task` and `Validation report writer`
  are `ERROR`, with `guardrail_passed 0.00` on all three attempts. Three of the
  87 observations are ERROR-level and all three are this failure.
- **Is it finished:** **yes** — closed at 49.94s, `status "completed"`,
  `run_succeeded: 1`, `run_metrics.reason "run_completed"`. Not paused at a gate,
  not still running.

The gap between the last two bullets is the finding that matters. A reader who
stops at the sessions list sees a 50-second run costing **$0.00** (F4). A reader
who stops at the trace header sees `run_succeeded: 1` and a green
`completed`. Only a reader who scrolls the tree to the bottom finds that the
node which produced the deliverable exhausted its retries and consumed most of
the budget doing it. **The console reports the run's outcome accurately and its
quality only if you go looking** — and because prompts and completions are
deliberately absent (F6), even then it can say that the report guardrail failed
but never why.

Two further cautions for anyone repeating this: **read a run a few minutes after
it ends**, or the totals will be wrong by a quarter (F1); and **prefer the
Langfuse cost to the app's own**, because `cost_source` says `openrouter-billed`
while `run_metrics.cost_usd` is an app snapshot taken 13% early (F5).
