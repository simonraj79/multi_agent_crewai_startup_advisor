# Observability audit — what exists today, and where each gap can be closed

**Task 1 synthesis, 2026-09-05.** Sources: [`audit/langfuse-inventory.md`](audit/langfuse-inventory.md),
[`audit/openrouter-forwarding.md`](audit/openrouter-forwarding.md),
[`audit/app-surface.md`](audit/app-surface.md). Every figure below was re-run
against the evidence file it cites; paths are relative to
`docs/observability/evidence/audit/`. Nothing was changed in Langfuse, in
OpenRouter or in the codebase by any of the three passes.

---

## 1. Method

| Inspected | By which source | Why that source |
| --- | --- | --- |
| Langfuse counts, field null-rates, metadata keys, per-trace JSON, cost arithmetic | Langfuse **public API**, HTTP basic auth, two snapshots (`12:49Z`, `13:00Z`) | countable and exact; `calculatedTotalCost` / `inputPrice` / `modelId` are API-only |
| Which Langfuse surfaces are used vs empty; how a trace renders | Langfuse **console**, 19 `.jpg` captures | Playground, Alerts, Integrations, Dashboards have no public API |
| OpenRouter broadcast destination's exact prior state | **management API** `GET /api/v1/observability/destinations`, corroborated by three editor screenshots | the API is authoritative; the UI renders a summary |
| What the broadcast promises | **docs**, saved verbatim (`openrouter/docs/*.md`) | to diff promise against arrival |
| What actually crosses the wire | **7 live probes** to `POST /chat/completions`, read back in Langfuse | the docs are silent or wrong on five points (below) |
| Where the app already holds run/agent/task/tool/model/cost | **codebase**, read-only, cited `file:line`; CrewAI 1.15.18 enumerated by running the installed package | not derivable from documentation |

**Where UI and API disagreed, and why each is not a contradiction**

- **Totals.** API snapshot 1 = **40 traces / 80 observations** at `12:49Z`
  (`langfuse/api-traces-all.json`, `api-observations-all.json`); console Home =
  **45 / 93** at `13:00Z` (`langfuse/console-11-home-dashboard-totals.jpg`).
  The delta is five probe traces a sibling worker wrote *during* the audit
  (§6.1 of the Langfuse inventory), not a counting error — snapshot 2 also
  answers 45 (`langfuse/api-traces-recheck.json`).
- **Traces vs observations.** The console's default Tracing table lists
  **observations** ("Total ≈ 93") while Home says **45 traces**. Two correct
  numbers that read as a contradiction.
- **Cost.** API `metrics_daily` `0.1839257` (snapshot 1; re-summed from
  `api-observations-all.json` to `0.1839257`, exact) vs console **"$0.18"** —
  console rounding.
- **Docs vs arrival — five findings, all from probes** (`openrouter/part3-field-mapping.json`):
  `span_name` is documented as creating an intermediate span and **creates
  nothing**; top-level `tags` **never arrives**; `trace.tags` arrives only as an
  ordinary metadata key, `trace.tags` in Langfuse stays `[]`; `release` arrives
  observation-level only, `trace.release` stays null; and the docs never state
  how a caller-supplied `trace_id` becomes a Langfuse trace id — measured as
  `sha256(s).hexdigest()[:32]`, re-verified here on 3 of 3 published cases plus
  the observation-id function `sha256(gen-id)[:16]`.
- **The destinations API omits `regions`.** Global-only is read from
  `openrouter/part1-destination-edit-regions-metadata-privacy.jpg` and restated
  in `part3-field-mapping.json`; it is not in
  `part1-destinations-api.json`. §6 marks it as the one screenshot-sourced row.
- **Clock.** Console renders UTC+8, API returns UTC — the `12:11:53Z` trace
  reads `20:11:53` on screen.

**Probe cost: `$0.0000894`**, 7 calls / 6 billable generations, all
`google/gemini-3.5-flash-lite:nitro` at `max_tokens: 8`, from OpenRouter's own
`GET /api/v1/generation` records — **0.18% of the $0.05 authorisation**
(`openrouter/part3-openrouter-generation-records.json`, `total_billed_usd:
8.94e-05`, re-read). The Langfuse pass and the codebase pass called no model
and spent `$0`.

---

## 2. What one trace is today

**One trace = one completed OpenRouter chat-completion request.** Nothing else
in this system produces one. All 40 app-and-neighbour traces in snapshot 1 have
an identical two-node shape, verified by re-count: **40 GENERATION + 40 SPAN**,
`parentObservationId` set on every SPAN and null on every GENERATION, no third
node type, no `EVENT` observation anywhere (`langfuse/api-observations-all.json`).

```
TRACE  7dacd2d95c23ebbe116edb0c908367c1   name "OpenRouter Request"   env default
│      userId null · sessionId null · tags [] · release null · scores []
└── GENERATION "LLM Generation"  google/gemini-3.8-flash  in 1673 / out 1006
    │   $0.00502725 · latency 7.588s · TTFT 2.239s · level DEFAULT · statusMessage null
    │   input = the full messages array · output = {completion, reasoning, rawRequest}
    └── SPAN "provider attempt 1: Google"  {attempt_index: 0, status_code: 200}
```

Re-verified across all 40: `name` is the constant `"OpenRouter Request"`,
`environment` is always `"default"`, `userId` / `sessionId` are **0/40**, `tags`
is **0/40**, and observation `level` is `DEFAULT` **80/80** with
`statusMessage` null **80/80**. The only field that separates this application
from its neighbours is `metadata["openrouter.api_key_name"]`.

**The 12:11 validator run** (`langfuse/analysis-validator-run-12-11.json`,
re-summed): ten calls, **32,959 input / 8,896 output tokens, `$0.048839`**,
`12:11:19.207Z` → `12:11:53.856Z` = **34.6 s from first call start to last call
start**. Roles in order: Scoper → three concurrent branch analysts, each taking
a tool-call turn then a continuation → Synthesist → Reporter → CrewAI Guardrail
Agent. The Reporter alone is **39.8%** of the run's cost (`$0.01944225` on
4,138 output tokens). Trace ids proving the shape:
`7dacd2d95c23ebbe116edb0c908367c1` (Scoper, plain turn),
`a2579573decfda4258eadda1a305571e` (branch tool-call turn, `output.completion`
empty), and for the whole ten, the `trace_id` field of each row in
`analysis-validator-run-12-11.json`.

**How it was reconstructed, exactly.** Two ad-hoc steps, neither of which is a
mechanism:

1. **Timestamp gaps.** A >120 s gap splits snapshot 1's 40 traces into 12
   clusters (`langfuse/analysis-trace-timeline.json`); cluster 12 *is* the run.
2. **A regex over prompt text.** The agent column is a `re.match` on the first
   line of `input.messages[0].content`, because `observation.name` is the
   constant `"LLM Generation"` and `trace.name` is the constant `"OpenRouter
   Request"` on all 40.

**Why that method does not generalise — three measured reasons.**

- **Concurrency breaks the clustering.** Snapshot 1 already contains 16
  overlapping wall-clock pairs; calls 2 and 3 of this very run start **23 ms
  apart** and overlap for their whole duration, because the three research
  branches are concurrent by design. Two runs launched together would produce
  two interleaved sequences of identically-named traces and the gap rule would
  **silently merge them and report one run at double the cost**.
- **It depends on the project being idle.** The 120 s threshold is a property
  of this dataset — one day, 40 traces, three applications — not of the system.
- **There is no groupable field to fall back on.** `sessionId`, `userId`,
  `tags`, `release`, `version` and `externalId` are null or empty on **40/40**,
  and the two names are constants. Langfuse offers no `Group by` and no `where`
  clause that reaches inside prompt text.

---

## 3. What a person can and cannot learn from the current data

"Answerable by a human reading prompt text" is **PARTIAL**, never YES.

| Question | Answerable today? | How, or why not | Evidence |
| --- | --- | --- | --- |
| **Cost per agent** | **PARTIAL** | The roll-up is real and exact, but it is produced by a regex over `input.messages[0].content` on a run a human identified by hand. `observation.name` is `"LLM Generation"` on all 40; no console `Group by` and no API `where` can reach prompt text. | `langfuse/analysis-validator-run-12-11.json`; `api-observations-all.json` |
| **Cost per flow / per run** | **PARTIAL** | Only by >120 s timestamp clustering, which works because the project is nearly idle and fails under concurrency (§2). No `run_id`, `workflow_id` or `session_id` reaches Langfuse: 0/40. | `langfuse/analysis-trace-timeline.json`; `api-traces-all.json` |
| **Which step failed, and why** | **NO** | No failure is representable. 80/80 observations `level: DEFAULT`, 80/80 `statusMessage: null`, 40/40 SPANs `status_code: 200`. A call the app retries, or that fails a guardrail, or that OpenRouter refuses, produces **no trace at all** — failure appears as an absence, and an absence cannot be counted or alerted on. | `langfuse/api-observations-all.json`; `openrouter/part3-field-mapping.json` (probe e: HTTP 400 → no trace, no observation, no error record) |
| **Why was a run slow** | **PARTIAL** | Per call, well: `latency`, `timeToFirstToken`, `completionStartTime` on every GENERATION, and the SPAN separates OpenRouter routing from provider service time (call 9 = 11.46 s of the run). Between calls, nothing: the 5.4 s gap between call 7 ending and call 8 starting is CrewAI orchestration and tool execution, and **only LLM calls are traced**. | `langfuse/analysis-validator-run-12-11.json`; `api-trace-C-validator-reporter.json` |
| **Which prompt produced a bad output** | **YES** | The strongest capability present. Full `messages` in (429–29,519 chars observed), full `completion` out, the model's `reasoning`, and `output.rawRequest` carrying `temperature`, `max_tokens`, the whole `response_format` schema and `reasoning.effort`. What is *missing* is which agent/task/version it belongs to — that is the row above. | `langfuse/api-trace-A-validator-scoper.json`, `api-trace-C-validator-reporter.json` |
| **Is quality drifting** | **NO** | No instrument exists: 0 scores, 0 score configs, 0 evaluators, 0 datasets, 0 experiments, 0 annotation queues, and the Playground has no LLM connection, so Langfuse's own LLM-as-judge cannot be run either. One day of data, so no baseline to trend against. | `langfuse/api-surfaces.json` (`scores`, `scores_v2`, `score_configs` all `totalItems: 0`); `console-08`, `console-12`, `console-19` |
| **Are two concurrent runs separable** | **NO** | Reasoned from field availability and labelled as such — only one application run exists in the whole project, so a concurrent pair was never observable. No correlating field (0/40 on all six), calls within a single run already interleave (16 overlapping pairs), so two runs would interleave with nothing to split them. | `langfuse/api-traces-all.json`; `analysis-trace-timeline.json` |
| **Is a failed LLM call visible** | **NO** | Measured, not inferred: an invalid model id returned HTTP 400 and produced no generation id, no trace, no observation and no error record. **NOT CHECKED**: a request that reaches a provider and *then* fails (5xx, timeout, content filter) — probe e died at OpenRouter's validation layer, before routing. | `openrouter/part3-field-mapping.json`; `part3-probe-requests-and-responses.json` |
| **What tool did the agent call** | **PARTIAL, and one trace late** | On a tool-call turn `output.completion` is `""` and **no `tool_calls` field appears at all**; the chosen query surfaces only in the *next* trace's input, as the `assistant` message the continuation was given. The tool's execution, result, latency, failure and retries are never anywhere — Firecrawl, HN Algolia and GitHub raise no OpenRouter request. | `langfuse/api-trace-B-validator-toolcall.json` (trace `a2579573decfda4258eadda1a305571e`) |
| **Whose traffic is this** | **PARTIAL** | Splitting works, but only as a metadata query nothing uses: `openrouter.api_key_name` divides snapshot 1 into `WikiSkills` 16, `LTA_ML_PROBLEM` 14, **`MultiAgentCrewAI` 10** — re-counted. The console offers no filter for it, because it is metadata rather than a first-class field. **$0.048839 of the project's $0.1839257 is this app — 27%.** | `langfuse/api-traces-all.json`; `openrouter/part3-langfuse-24h-survey.json` |

Two more that the data answers outright and are worth keeping: **which model,
provider, endpoint and permaslug served each call, at what per-stage latency**
(the richest thing in the dataset — provider `Google` 31 / `Google AI Studio`
9), and **whether a response was truncated** — one trace of 40 carries
`openrouter.finish_reason: "MAX_TOKENS"` (`9e491d1f614ab648f318c4dad34a84d3`,
foreign traffic), though its `level` is `DEFAULT` and `statusMessage` null like
every other, so it is invisible to any level- or status-based filter and
findable only by a metadata query.

---

## 4. Which gaps are fixable at the OpenRouter layer, and which require the app

| Gap | OpenRouter mechanism, with the probe that proved it — or why not |
| --- | --- |
| **A run identifier reaching Langfuse** | **FIXABLE, three ways, not equivalent.** (a) `trace.trace_id` makes the run id *the trace*: probes d1 and d2 were two separate requests and became **one trace with both generations**, id `8b15b51c4f6c36711f217e68ad5c99ac` = `sha256("obsprobe-trace-1788612874")[:32]`, re-verified. (b) top-level `session_id` → first-class `trace.sessionId`, grouping traces without merging, and it also fixes sampling to include/exclude a whole run together. (c) `trace.run_id` (any arbitrary key) → `trace.metadata.run_id` **and** `observation.metadata.run_id`, filterable. **Only if the app puts it in the body of every request.** |
| **Two requests of one run being recognised as one run** | **PARTIAL, and this is the sharp finding.** Two probe traces both carrying `metadata.run_id = obs-probe-run-1788612874` — `dbd49206c2c8a478fcf97ce967645760` and `8b15b51c4f6c36711f217e68ad5c99ac` — **stayed two traces** (re-read from `langfuse/api-traces-recheck.json`). A shared `run_id` in metadata groups by filtering, never by merging; only a shared `trace.trace_id` merges. |
| **Agent role / task name on a call** | **FIXABLE, if the app sends them.** `trace.agent_role` and `trace.task_name` arrive verbatim including spaces as observation metadata. In the merged d1+d2 trace the two observations correctly carry **different** values (`Market evidence analyst`/`market_task` and `Sentiment signal analyst`/`sentiment_task`) while **trace-level metadata holds only one of them** — last write wins. So per-call attribution survives a merge; trace-level attribution does not. |
| **App spans and OpenRouter generations in one hierarchy** | **FIXABLE in principle, every ingredient verified, end to end NOT VERIFIED.** `parent_span_id` is stored verbatim as `parentObservationId` (probe used `0123456789abcdef`, an observation that does not exist; Langfuse tolerated it and rendered at the trace root). The trace id is a pure function of a string, so the app can compute it off-line. No app-side span was written in this audit — the app has no Langfuse SDK and `grep -rn langfuse src/ pyproject.toml` returns **0**, re-run. |
| **An intermediate span between trace and generation** | **NOT available from OpenRouter.** `span_name` is documented to create one and creates nothing; the string survives only inside the echoed `output.rawRequest`. Any grouping level between trace and generation must be written by the app. |
| **Langfuse tags / `trace.release`** | **NOT available.** Neither spelling of `tags` becomes a Langfuse tag; `release` lands observation-level only. Both are app-side (or not worth having). |
| **Separating this app's traffic from the workspace's** | **FIXABLE at OpenRouter, one field.** The destination's `api_key_hashes` is `null` = all keys, so it broadcasts every request the workspace makes; the Included/Excluded API Keys control exists and is unset. Measured consequence: 30 of 45 traces in the last 24 h are two unrelated applications. |
| **Which step failed** | **STRUCTURALLY IMPOSSIBLE at OpenRouter.** A request OpenRouter refuses produces no trace at all (probe e). A CrewAI guardrail rejection, an agent giving up, a `HookAborted` cost abort and a cancelled run all happen with no HTTP request to refuse. |
| **Tool executions** | **STRUCTURALLY IMPOSSIBLE.** The docs' "Tool Usage" means *the model asked*. The tool running is a function call inside this process — Firecrawl, HN Algolia, GitHub. No HTTP request reaches OpenRouter, so arguments, result, latency, failure and retries are all invisible. The repo's own tool envelopes (`status`, `query`, `result_count`, `notes`) exist entirely outside anything OpenRouter can see. |
| **Agent and task boundaries** | **STRUCTURALLY IMPOSSIBLE.** In the probe traces `agent_role` and `task_name` are present *only* because they were typed into the request body. Nothing in an OpenAI-schema request says two calls belong to one CrewAI task. |
| **Retries that matter** | **STRUCTURALLY IMPOSSIBLE.** OpenRouter models only its own provider retries (`provider attempt 1: Google`, `provider_responses[]`). A guardrail regeneration or an agent loop iteration is a *fresh* request with a fresh generation id, unrelated to the one before it — five guardrail attempts are five unrelated traces unless the app supplies a shared identifier. |
| **Run start, run end, gate waits, cancellation** | **STRUCTURALLY IMPOSSIBLE.** Traces are emitted "asynchronously after requests complete" — no start event, no end event. A run paused at a human gate for an hour emits nothing, because nothing is being asked of a model. Cancellation happens between calls. |
| **Anything that is not a chat completion** | **STRUCTURALLY IMPOSSIBLE.** All 45 traces are chat completions; OpenRouter's own Logs page shows `Gemini Embedding 2` generations over the same window with no Langfuse counterpart. Embeddings, Cohere rerank and Firecrawl are absent from the traces and from the cost total. *(Measured on another workload's generations; **NOT VERIFIED by direct probe**.)* |
| **Per-node cost, owner, verdict, dropped-frame counts** | **STRUCTURALLY IMPOSSIBLE — the app already has all of it.** `run_node_metrics` is keyed `(run_id, node_id, model)`; `user_id` is on the run row; the deterministic `Verdict` and the capture counters are frames. OpenRouter can total an API key, never a node. |

**The settled sessions answer.** A run identifier **can** reach Langfuse through
OpenRouter — proven three ways, at zero SDK cost — **but only if the application
puts it in the request body on every single call**, which is an app change on
the wire, not a console setting. And it buys grouping only: failures, tool
calls, agent/task boundaries, gates, cancellation and non-LLM spend can never
come from OpenRouter, at any configuration. Content is the mirror of that: it
already crosses in full (`privacy_mode: false`), including `output.rawRequest`,
the caller's entire JSON body echoed verbatim — a disclosure surface for
anything the app ever puts in a request body.

---

## 5. Every Langfuse surface, used or empty

Project `cmto3mj7t06ykad0ipon3ksbw`, `us.cloud.langfuse.com`, Langfuse v4.30.0,
plan Hobby. One line each, from `audit/langfuse-inventory.md` §4.

- **Tracing** — **USED**, and the only populated surface: 45 traces / 93 observations, all on one day (`console-02`).
- **Sessions** — empty of app data; the single row is a sibling worker's probe (`console-06`).
- **Users** — empty of app data; the single row is that same probe (`console-07`).
- **Scores** — **empty**: no scores, no score configs, no analytics (`console-08`, `api-surfaces.json`).
- **Evaluators (LLM-as-judge)** — none configured, onboarding screen only (`console-12`).
- **Human Annotation** — no queues (`console-14`).
- **Prompts** — empty; no managed prompts, 0 automations (`console-09`).
- **Datasets** — empty (`console-10`).
- **Experiments** — empty, "No results", 0 pages (`console-17`).
- **Dashboards** — 5, **all owned by "Langfuse"** (Agent, Home, Cost, Latency, Usage Management); zero user-created, zero custom widgets (`console-13`).
- **Home** — renders: 45 traces, $0.18, 93 observations, "Scores: No data" (`console-11`).
- **Alerts** — none; no Slack / Webhook / GitHub Actions destination and no rule (`console-18`).
- **Playground** — **unusable, "No Model Configured"**, no LLM API key set in the project (`console-19`) — and load-bearing, because LLM-as-judge evaluators run through that same connection.
- **Settings → Model Definitions** — 182 definitions, every one `isLangfuseManaged: true`; no project-local override or price correction (`console-15`, `api-models-all.json`).
- **Settings → Integrations** — none connected; PostHog, Mixpanel, Blob Storage (plan-gated), Slack, Web Callouts all show "Configure" (`console-16`).

---

## 6. OpenRouter-side prior configuration — the F1 record

Exact baseline, copied from `audit/openrouter-forwarding.md` §1, read from
`GET /api/v1/observability/destinations` and corroborated against the editor
screens. **Nothing was changed; this is the state to diff against.**

| Setting | Value |
| --- | --- |
| Feature master switch | **Broadcast: ON** |
| Sibling feature | **Input & Output Logging: ON** (Beta) — OpenRouter's own log store, separate from broadcast |
| Destinations configured | **1** (`total_count: 1`) |
| Type | `langfuse` |
| Destination id (API) | `8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b` |
| Destination id (UI route) | `15910` |
| Workspace | `d9782653-59a8-51a5-9ff4-b28da297b63f` ("Default Workspace") |
| Name | `multi-agent-crew-ai` |
| `enabled` | `true` |
| Langfuse host | `https://us.cloud.langfuse.com` |
| Public key | returned pre-masked, `pk-l…`, 11 characters; nothing beyond `pk-l` is legible anywhere |
| Secret key | masked, 11 characters, never rendered |
| Custom headers | none |
| **Regions** | **Global ✅ · European Union ☐ · United States ☐** — only traffic to `https://openrouter.ai` is forwarded |
| **Privacy Mode** | **☐ OFF** → prompts and completions **are** sent |
| **Additional generation metadata → Cost (15 fields)** | **☐ OFF** (`broadcast_generation_cost: false`) |
| **Additional generation metadata → Identity (18 fields)** | **☐ OFF** (`broadcast_generation_identity: false`) |
| **Additional generation metadata → Request context (19 fields)** | **☐ OFF** (`broadcast_generation_request_context: false`) |
| Sampling rate | `1` (100%) |
| Included / Excluded API keys | none selected |
| `api_key_hashes` | `null` — documented as "all keys" |
| `filter_rules` | `null` — "No filter rules configured. All traces will be sent" |
| Created / updated | `2026-09-05T08:24:27.107Z` / `2026-09-05T08:24:50.201Z` |

Re-read from `openrouter/part1-destinations-api.json`: every row above except
**Regions** appears verbatim in that JSON. `regions` is **not** a field of the
destinations API response — Global-only is sourced from
`openrouter/part1-destination-edit-regions-metadata-privacy.jpg` and restated
as `"regions": ["global"]` in `openrouter/part3-field-mapping.json`. Two further
facts belong to the baseline: the destination row's menu offers **Edit · Status
· Send Trace · Disable · Delete**, and `Send Trace` was **not** pressed; and the
editor's own wording on the Identity category — *"Privacy mode does not remove
these identity fields when enabled."*

**Changes made by this audit: none.** Any change and its reason is recorded by
whoever makes it, against this table.

---

## 7. The layer decision

**Decision: REPLACE.** The OpenRouter-side broadcast stops forwarding this
app's API key (and only this key), and the app emits every Langfuse observation
itself — trace, run, node, task, agent, tool, generation, gate, scores — from
its existing frame pipeline, per [`TRACE-CONTRACT.md`](TRACE-CONTRACT.md).

Two analysts argued the question independently, one seeded with SUPPLEMENT and
one with REPLACE ([`audit/position-A.md`](audit/position-A.md),
[`audit/position-B.md`](audit/position-B.md)). Both landed on REPLACE, and
both, separately, found the same misreading in the Langfuse inventory
(corrected in place). The orchestrator's reasons, in order of weight:

1. **The app must emit generations anyway.** OpenRouter forwards nothing for a
   refused request (probe e) and nothing about tool calls, so failed calls and
   tool use have to come from the app. Once the app writes failed generations,
   the OpenRouter copy covers only the success branch, and keeping it means
   two emitters for one kind of observation — exactly what E1 forbids.
   `LLMCallFailedEvent` carries no `response_id`, so under SUPPLEMENT the app
   could not even tell whether OpenRouter also held a record of a given call.
2. **Every identity value already sits on the frame.** Agent role, task name,
   tool name, node id, model, tokens, cost estimate and the OpenRouter
   `response_id` are on the app's frames today, with nothing flow-specific in
   the frame contract. Stamping those onto the wire per request (SUPPLEMENT)
   would touch eight `LLM(...)` construction sites and every future flow —
   the generalisation hole rows C1/C2 exist to close.
3. **The join SUPPLEMENT needs is fragile.** It rests on an undocumented
   `sha256(trace_id)[:32]` derivation, a parent span id that the async
   exporter has not created when the model call starts, and an ingestion
   guarantee about late parents that Langfuse does not document.
4. **The content policy cannot be met with the broadcast on.** With Privacy
   Mode off the whole request body is echoed into `trace.output.rawRequest` by
   a third party, which is where a pasted key would land; E3 becomes untestable
   from inside this repository.
5. **The one thing the broadcast had that the app lacks — the true billed cost
   and the serving provider — is one lookup away.** `GET /api/v1/generation`
   answers in ~0.5 s with `total_cost`, native reasoning/cached tokens and the
   provider attempts; the exporter resolves it off-thread and writes it onto the
   generation before the span closes.

What REPLACE gives up, stated plainly: a free cross-emitter canary (the only
independent check of the app's figures is now OpenRouter's own generation
records, which is what E5 uses); the OpenAI SDK's two silent transport retries
stay invisible to everyone; and CLI runs (`validate --idea`), which never enter
the service's capture scope, stay untraced — a follow-up, not this programme.

**OpenRouter-side change:** add the `MultiAgentCrewAI` key to the destination's
*excluded* API keys on `8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b`. Not disabled, not
Privacy Mode: the owner's two other apps in the same workspace keep forwarding.
Prior state is §6 above; the change and its probe proof are in
[`audit/openrouter-change.md`](audit/openrouter-change.md).

## 8. Definition-of-done revisions this audit justifies

Logged in `DEFINITION-OF-DONE.md` §7 with the same wording.

- **§5.1 trace id.** The app's `run_id` is a uuid4, so the Langfuse trace id is
  `UUID(run_id).hex` (32 hex) when the run id parses, else the SDK's seeded
  derivation. Reason: no undocumented hash in the critical path; the id stays
  computable off-line from a console URL.
- **§5.5 one reporter per call → settled as REPLACE** (this section). E1's
  evidence gains the recorded OpenRouter exclusion and its probe.
- **B4 timing method.** The Langfuse SDK cannot set an observation's start time,
  so span starts are the exporter's clock behind a ≤ 0.25 s drain, ends are the
  frame's own timestamp, and `metadata.frame_ts` carries the true start. The
  1 s tolerance stands.
- **B1/B2 usage split.** The app's frames drop cached/reasoning token counts; the
  exporter fills them from the OpenRouter lookup. The frame serializer is not
  changed (scope).
- **No new rows.** The audit found nothing the existing rows fail to cover; the
  three things it found outside the brief are in §9.

---

## 9. Findings outside the brief

Things the inventories flagged that this programme will not fix. One line each.

- **The `metrics/daily` endpoint the cost figures came from is deprecated** — it returns a `_deprecation` block naming a **sunset of 2026-11-16** and directs callers to `GET /api/public/v2/metrics`; anything built on it has a ten-week shelf life (`langfuse/api-surfaces.json`). The replacement was **NOT** exercised.
- **The Langfuse Playground has no model configured**, so LLM-as-judge evaluators are not merely unused but unreachable without adding an LLM key to the project (`langfuse/console-19-playground-no-model.jpg`).
- **Two thirds of the project is not this application** — `WikiSkills` 16 and `LTA_ML_PROBLEM` 14 against `MultiAgentCrewAI` 10 in snapshot 1, re-counted, because the broadcast destination is workspace-scoped (`langfuse/api-traces-all.json`, `openrouter/part1-api-key-inventory.json`). Any figure read off Langfuse Home is the owner's whole OpenRouter account.
- **A CLI run has no capture scope at all.** `grep -rn capture_events src/brief_crew` answers `service/registry.py:2694` and nothing else; `validate` builds a `ValidatorFlow` and kicks it off directly, never through `RunRegistry` — so a CLI run emits no frames, has no `run_id`, and would be invisible to any frame-attached exporter (`audit/app-surface.md` §1.2).
- **`CLAUDE.md`'s claim that the generation id "never reaches the process" is stale.** `response_id` is a declared field on `LLMCallCompletedEvent` and this repository **already writes it onto the LLM `after` frame** — re-read at `src/brief_crew/events/serializer.py:525`. It also reaches Langfuse as `gen_ai.response.id`. What remains true is the narrower claim the docstring makes about `_extract_openai_token_usage`'s five-key whitelist.
- **127 of CrewAI 1.15.18's 163 `BaseEvent` subclasses are ignored** by the serializer's isinstance ladder and merely counted (`app/adapter-handled-vs-ignored.txt`, `crewai-event-classes.txt`, both re-read). The lifecycle families are handled comprehensively; **Memory (10), Knowledge (7) and Reasoning (3)** are handled not at all, and a *successful* MCP tool call is entirely invisible — only `MCPConnectionFailedEvent` is mapped.
- **The OpenAI SDK's own transport retries are invisible everywhere.** `OpenAICompletion.max_retries = 2` is passed to the client and those retries happen inside the HTTP layer: no CrewAI event, no frame, no token frame, and no second OpenRouter trace. A 429 retried twice and then succeeding looks like one call that took a long time (`audit/app-surface.md` §5.4).
- **`/api/public/dataset-run-items` answers 400**, not an empty list, when called without required params — the only non-200 among sixteen probed Langfuse endpoints (`langfuse/api-surfaces.json`).
- **`openrouter.entity_id` and `openrouter.creator_user_id`** (identical, constant across all 45 traces) are an OpenRouter **account** identifier present in the exported JSON in this evidence tree — not a credential, but worth knowing before the tree is shared.
- **The probe traces are permanent.** Five `obs-probe-*` traces carrying the marker `1788612874` are now in the project and will be counted by anyone measuring later; they are cheap to find and delete.

---

**Summary.** Today Langfuse holds one trace per completed OpenRouter chat
completion — rich in prompt, completion, model, provider and latency, and
carrying no run, agent, task, tool, failure or score — so the only questions it
answers cleanly are "which prompt produced this output" and "which model served
it at what latency"; everything about a *run* is reconstructed by hand and
breaks the moment two runs overlap.

An app-side run identifier can reach Langfuse through OpenRouter and would fix
grouping and per-call attribution, but failures, tool executions, agent and task
boundaries, gate waits, cancellation and non-LLM spend are structurally
unavailable at that layer at any configuration.
