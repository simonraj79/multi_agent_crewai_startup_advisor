# Langfuse inventory — project `cmto3mj7t06ykad0ipon3ksbw`

**Audited 2026-09-05.** Host `us.cloud.langfuse.com`, Langfuse **v4.30.0**, organisation
*Simon's Organization* (`cmto3mj7p06ygad0idol4zloj`), project name **"My Project"**, plan
**Hobby**. Read-only audit: nothing was created, modified or deleted in Langfuse, and no
model was called for money by this pass.

Every claim below points at a file in
[`../evidence/audit/langfuse/`](../evidence/audit/langfuse/). Where a number is not backed
by a file, it says NOT CHECKED and why.

> **Credentials.** `LANGFUSE_BASE_URL` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` were
> read from `D:\MultiAgentSystem\.env` into a script's process environment via
> `python-dotenv`. No key value was printed, logged, screenshotted or written to any
> artifact, and none appears in this document or in the evidence tree.

> **Screenshots are `.jpg`, not `.png`.** The browser tool's `screenshot` action emits JPEG
> and offers no format choice; the files were copied verbatim rather than re-encoded, so
> the extension states what the bytes are. Nineteen console captures are present.

---

## 1. Method — which source answered what

| Question | Answered by | Why that source |
| --- | --- | --- |
| Counts, dates, field null-rates, metadata keys, per-trace JSON | **Public API** | Countable and exact; the console paginates and rounds |
| Cost arithmetic, model-definition matching | **Public API** | `calculatedTotalCost` / `inputPrice` / `modelId` are API-only fields |
| Which feature surfaces are used vs empty | **Console** | Several surfaces (Playground, Alerts, Integrations, Dashboards) have no public API |
| Whether Langfuse-managed model defs are overridden locally | **Both** | API `isLangfuseManaged`, console *Settings → Model Definitions* |
| Trace/observation rendering, what an operator actually sees | **Console** | Not derivable from JSON |

API base `${LANGFUSE_BASE_URL}`, HTTP basic auth public:secret. Console at
`https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/...`, signed in as
`simoraj@gmail.com`. **No login wall was hit** — the session was already authenticated.

**Two API snapshots were taken, deliberately**, because the console showed rows that the
first snapshot did not (§6.1):

- **Snapshot 1** — `12:49Z`, [`api-traces-all.json`](../evidence/audit/langfuse/api-traces-all.json)
  (40 traces), [`api-observations-all.json`](../evidence/audit/langfuse/api-observations-all.json) (80 observations).
- **Snapshot 2** — `13:00Z`, [`api-traces-recheck.json`](../evidence/audit/langfuse/api-traces-recheck.json) (45 traces).

Unless a row says otherwise, **the numbers below are snapshot 1**, because that is the
state the observation-level export corresponds to.

---

## 2. Numbers

| Quantity | Snapshot 1 (12:49Z) | Snapshot 2 (13:00Z) | Console | Evidence |
| --- | ---: | ---: | ---: | --- |
| Traces | **40** | **45** | 45 | `api-traces-all.json`, `api-traces-recheck.json`, [console-11](../evidence/audit/langfuse/console-11-home-dashboard-totals.jpg) |
| Observations | **80** | 93 (via `metrics/daily`) | 93 | `api-observations-all.json`, [console-11](../evidence/audit/langfuse/console-11-home-dashboard-totals.jpg) |
| Observations per trace | **exactly 2, all 40** | — | — | `api-observations-all.json` |
| Total cost (USD) | **0.1839257** | 0.1840151 | $0.18 | `api-surfaces.json` → `metrics_daily`, [console-11](../evidence/audit/langfuse/console-11-home-dashboard-totals.jpg) |
| Distinct trace names | **1** (`OpenRouter Request`) | 3 | 3 | `api-traces-all.json` |
| Date range | 2026-09-05 `10:49:03.732Z` → `12:11:53.856Z` | → `12:54:45.536Z` | same day | `analysis-trace-timeline.json` |
| Days with data | **1** (2026-09-05 only) | 1 | 1 | `api-surfaces.json` → `metrics_daily` (`totalItems: 1`) |
| Environments | **1** (`default`) | 2 (`default` 44, `obsprobe-env` 1) | 2 | `api-traces-recheck.json`, [console-02](../evidence/audit/langfuse/console-02-traces-list.jpg) |
| Sessions | **0** | 1 | 1 | `api-surfaces.json`, [console-06](../evidence/audit/langfuse/console-06-sessions.jpg) |
| Users | **0** | 2 traces carry one | 1 | `api-surfaces.json`, [console-07](../evidence/audit/langfuse/console-07-users.jpg) |
| Scores | **0** | 0 | 0 | `api-surfaces.json` (`scores`, `scores_v2`, `score_configs` all `totalItems: 0`), [console-08](../evidence/audit/langfuse/console-08-scores-empty.jpg) |
| Prompts / Datasets / Comments / Annotation queues | **0 each** | 0 | 0 | `api-surfaces.json`, [console-09](../evidence/audit/langfuse/console-09-prompts-empty.jpg), [console-10](../evidence/audit/langfuse/console-10-datasets-empty.jpg), [console-14](../evidence/audit/langfuse/console-14-human-annotation-empty.jpg) |
| Model definitions | **182, all `isLangfuseManaged: true`** | — | all "Clone"-only | `api-models-all.json`, [console-15](../evidence/audit/langfuse/console-15-settings-model-definitions.jpg) |

### Field population across the 40 app-and-neighbour traces (snapshot 1)

| Field | Non-null | Value |
| --- | ---: | --- |
| `name` | 40/40 | always the literal `"OpenRouter Request"` |
| `environment` | 40/40 | always `"default"` |
| `input` / `output` | 40/40 | full content — see §3 |
| `metadata` | 40/40 | 19 keys, all OpenRouter-supplied — see §3 |
| `public`, `bookmarked` | 40/40 | always `false` |
| **`userId`** | **0/40** | — |
| **`sessionId`** | **0/40** | — |
| **`release`** | **0/40** | — |
| **`version`** | **0/40** | — |
| **`tags`** | **0/40** | always `[]` |
| **`externalId`** | **0/40** | — |
| **`scores`** | **0/40** | always `[]` |
| Observation `level` | 80/80 | always `DEFAULT` |
| Observation `statusMessage` | **0/80** | always null |
| Observation `promptId` / `promptName` / `promptVersion` | **0/80** | always null |

### Token and cost totals by model (snapshot 1)

| Model | Traces | Input tok | Output tok | Cost |
| --- | ---: | ---: | ---: | ---: |
| `google/gemini-3.8-flash` | 34 | 98,690 | 26,716 | $0.1742025 |
| `google/gemini-3.5-flash-lite` | 6 | 14,594 | 2,138 | $0.0097232 |
| *(the 40 SPAN observations)* | 40 | 0 | 0 | $0 |

---

## 3. Anatomy of one trace, annotated

Every trace in this project is **one OpenRouter chat-completion request**. Full JSON for
five representatives is exported; the annotated one here is
[`api-trace-A-validator-scoper.json`](../evidence/audit/langfuse/api-trace-A-validator-scoper.json),
trace `7dacd2d95c23ebbe116edb0c908367c1`, rendered at
[console-03](../evidence/audit/langfuse/console-03-trace-detail-tree-and-input.jpg) /
[console-04](../evidence/audit/langfuse/console-04-trace-detail-output.jpg) /
[console-05](../evidence/audit/langfuse/console-05-trace-detail-metadata.jpg).

### The observation tree — always exactly two nodes, never more

```
TRACE  7dacd2d95c23ebbe116edb0c908367c1   name "OpenRouter Request"   env default
│      timestamp 2026-09-05T12:11:19.207Z   latency 7.588s   totalCost $0.00502725
│      userId null   sessionId null   tags []   release null   version null   scores []
│
└── GENERATION  id 7dacd2d95c23ebbe1        name "LLM Generation"
    │   model            google/gemini-3.8-flash
    │   modelId          c3a9f9a6-…-9f0f8204a709   → Langfuse def "gemini-3.8-flash"
    │   startTime        12:11:19.207Z
    │   completionStartTime 12:11:21.446Z        (= first token)
    │   endTime          12:11:26.795Z
    │   latency 7.588s   timeToFirstToken 2.239s
    │   usageDetails     {input: 1673, output: 1006, total: 2679}
    │   costDetails      {input: 0.00125475, output: 0.0037725, total: 0.00502725}
    │   calculatedInput/Output/TotalCost = the same three numbers
    │   inputPrice 7.5e-07   outputPrice 3.75e-06   totalPrice null
    │   level DEFAULT   statusMessage null   promptId/Name/Version null
    │   input  = {"messages":[{role:"system",…},{role:"user",…}]}   ← FULL text
    │   output = {"completion": …, "reasoning": …, "rawRequest": {…}}
    │
    └── SPAN  id …  parentObservationId = the GENERATION
            name "provider attempt 1: Google"
            latency 1.671s   model null   usage {} …   costDetails {}
            metadata {attempt_index: 0, status_code: 200, is_byok: false,
                      endpoint_id: …, model_permaslug: "google/gemini-3.8-flash-20260902"}
```

**All 40 traces have exactly this shape** — 40 GENERATION + 40 SPAN, one SPAN per trace,
`parentObservationId` set on every SPAN and null on every GENERATION, every SPAN
`status_code: 200`. There is no deeper nesting and no third node type: no `EVENT`
observations exist anywhere in the project.

### Is content captured? Yes — in full, both directions

- **`input`** is the complete `messages` array: every system prompt verbatim (429–29,519
  characters observed), every user message, and on continuation turns the `assistant`
  message *with its `tool_calls`* and the `tool` message *with the full JSON tool result*.
  Nothing is truncated or elided.
- **`output`** carries `completion` (the assistant text), `reasoning` (the model's thinking
  trace, present on 2 of the 10 app calls), and **`rawRequest`** — the request parameters
  OpenRouter received, minus nothing: `model`, `temperature`, `max_tokens`,
  `response_format` (including the full JSON schema), `reasoning: {effort}`, `stream`,
  `tools`, `tool_choice`, `provider` preferences, `_skin`.
- **One real gap:** on a turn where the model emits a **tool call**, `completion` is the
  empty string and **no `tool_calls` field appears in `output` at all**. See §5.

### Metadata — every key seen, aggregated across all traces

**Trace-level `metadata`, 19 keys, present on 40/40** (all OpenRouter-supplied):

`openrouter.source` · `openrouter.api_key_name` · `openrouter.entity_id` ·
`openrouter.creator_user_id` · `openrouter.provider_name` · `openrouter.provider_slug` ·
`openrouter.finish_reason` · `openrouter.input_unit_price` · `openrouter.output_unit_price` ·
`openrouter.router_latency_ms` · `openrouter.provider_request_ms` ·
`openrouter.provider_headers_ms` · `openrouter.first_token_ms` ·
`openrouter.provider_body_end_ms` · `openrouter.provider_time_to_first_token_ms` ·
`provider_responses` · `resourceAttributes` · `scope` · `attributes`

Three further keys appear **only** on the probe traces of §6.1 and never on app traffic:
`openrouter.user_id`, `run_id`, `agent_role`, `task_name`, `environment`, `release`, `tags`.

`metadata.attributes` is the OTel span, 30 keys, including
`gen_ai.response.id` (**the OpenRouter generation id**, e.g.
`gen-1788610279-n7uDHd8YKPC2n9oilLV3`), `gen_ai.provider.name`, `gen_ai.request.model`,
`gen_ai.response.model`, `gen_ai.response.finish_reason`, the six
`gen_ai.usage.{input,output,total}_{tokens,cost}` pairs, `gen_ai.usage.input_tokens.cached`
/`.audio`/`.video`, `gen_ai.usage.output_tokens.reasoning`/`.image`, and the four
`langfuse.observation.*` directives that drive ingestion.
`metadata.resourceAttributes` is `{service.name: "openrouter", openrouter.trace.id: <the
generation id>}`; `metadata.scope` is `{name: "openrouter", attributes: {}}`.

**So yes, OpenRouter-specific data is present and rich:** generation id, serving provider
name *and* slug (`google-vertex/global` on 31, `google-ai-studio` on 9), endpoint id, model
permaslug, per-stage latency breakdown, unit prices, BYOK flag, finish reason, and the
API key's *name*. What is **absent** is any app-side identifier: no HTTP-Referer, no
X-Title, no run id, no agent name as a field.

### Who computes the cost — ingestion payload, not Langfuse

The ingestion payload explicitly carries `langfuse.observation.cost_details`
(`{"input":0.00125475,"output":0.0037725,"total":0.00502725}`), and Langfuse's documented
rule is that an ingested cost wins over a computed one.

**But this cannot be proved from the data here, and I am not going to claim it is.** For
both models the OpenRouter unit price and the Langfuse model-definition unit price are
*identical* — `gemini-3.8-flash` $0.75/$3.75 and `gemini-3.5-flash-lite` $0.30/$2.50 — so
the two paths produce the same number to the last decimal on all 40 traces. Both models
**do** match a Langfuse definition (`modelId` is non-null on all 40 GENERATIONs and
resolves in `api-models-all.json`), so Langfuse *could* have priced them itself.

What follows regardless: **the cost figures inherit OpenRouter's blind spots.**
`openrouter.input_unit_price` is the base rate, and the three requests that used
`:nitro` (`rawRequest.provider = {sort: "throughput"}`, plus every probe request) still
report the base rate — so the `:nitro` price spread that
[`CLAUDE.md` item 41](../../../CLAUDE.md) warns about is **invisible here**, not bounded by
it. Reasoning tokens are billed inside `output` with no separate line
(761 of the Scoper's 1,006 output tokens were reasoning). Embeddings, rerank and Firecrawl
raise no OpenRouter LLM call and appear nowhere.

### Duplicates — none

40 distinct trace ids, 40 distinct `gen_ai.response.id` values, zero duplicate timestamps,
and zero repeated `(input_tokens, output_tokens, model)` signatures. Every SPAN is
`attempt_index: 0` and every trace has exactly one attempt, so no provider retry is
double-counted either. Evidence: `analysis-trace-timeline.json`.

---

## 4. Every Langfuse surface, and whether it is used

| Surface | State | Evidence |
| --- | --- | --- |
| **Tracing** | **USED** — the only populated surface. 45 traces / 93 observations, all one day | [console-02](../evidence/audit/langfuse/console-02-traces-list.jpg), `api-traces-*.json` |
| **Sessions** | Empty of app data. The single row is the §6.1 probe's | [console-06](../evidence/audit/langfuse/console-06-sessions.jpg), `api-surfaces.json` |
| **Users** | Empty of app data. The single row is the §6.1 probe's | [console-07](../evidence/audit/langfuse/console-07-users.jpg) |
| **Scores** | **Empty.** No scores, no score configs, no analytics | [console-08](../evidence/audit/langfuse/console-08-scores-empty.jpg), `api-surfaces.json` |
| **Evaluators (LLM-as-judge)** | **None configured.** Onboarding screen only | [console-12](../evidence/audit/langfuse/console-12-evaluators-empty.jpg) |
| **Human Annotation** | **No queues** | [console-14](../evidence/audit/langfuse/console-14-human-annotation-empty.jpg) |
| **Prompts** | **Empty.** No managed prompts, 0 automations | [console-09](../evidence/audit/langfuse/console-09-prompts-empty.jpg), `api-surfaces.json` |
| **Datasets** | **Empty** | [console-10](../evidence/audit/langfuse/console-10-datasets-empty.jpg), `api-surfaces.json` |
| **Experiments** | **Empty** ("No results", 0 pages) | [console-17](../evidence/audit/langfuse/console-17-experiments-empty.jpg) |
| **Dashboards** | 5 dashboards, **all owned by "Langfuse"** (Agent, Home, Cost, Latency, Usage Management). **Zero user-created**, zero custom widgets | [console-13](../evidence/audit/langfuse/console-13-dashboards-list.jpg) |
| **Home** | Renders — 45 traces, $0.18, 93 observations, "Scores: No data" | [console-11](../evidence/audit/langfuse/console-11-home-dashboard-totals.jpg) |
| **Alerts** | **None.** No Slack / Webhook / GitHub Actions destination, no alert rule | [console-18](../evidence/audit/langfuse/console-18-alerts-empty.jpg) |
| **Playground** | **Unusable — "No Model Configured", no LLM API key set in project** | [console-19](../evidence/audit/langfuse/console-19-playground-no-model.jpg) |
| **Settings → Model Definitions** | 182 definitions, **every one Langfuse-managed**; no project-local override or price correction | [console-15](../evidence/audit/langfuse/console-15-settings-model-definitions.jpg), `api-models-all.json` |
| **Settings → Integrations** | **None connected.** PostHog, Mixpanel, Blob Storage (plan-gated), Slack, Web Callouts all show "Configure" | [console-16](../evidence/audit/langfuse/console-16-settings-integrations.jpg) |

That the **Playground has no LLM connection** is load-bearing beyond itself: Langfuse's
LLM-as-judge evaluators run through that same connection, so the whole Evaluation half of
the product is not merely unused here — it is **not yet reachable** without adding a key.

---

## 5. What the current data CAN and CANNOT answer

The one complete application run in the project is the `12:11:19 → 12:11:53` cluster —
ten calls under API key `MultiAgentCrewAI`, reconstructed in
[`analysis-validator-run-12-11.json`](../evidence/audit/langfuse/analysis-validator-run-12-11.json):

| # | Time | Agent (read out of the system prompt) | Model | in | out | Cost | Turn shape |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | 12:11:19.207 | Startup validation scoper | 3.8-flash | 1673 | 1006 | $0.005027 | plain |
| 2 | 12:11:27.367 | Technical feasibility analyst | 3.5-flash-lite | 1692 | 26 | $0.000573 | **tool call, empty output** |
| 3 | 12:11:27.390 | Community demand analyst | 3.5-flash-lite | 1930 | 36 | $0.000669 | **tool call, empty output** |
| 4 | 12:11:29.367 | Market evidence analyst | 3.5-flash-lite | 2646 | 32 | $0.000874 | **tool call, empty output** |
| 5 | 12:11:30.705 | Community demand analyst | 3.5-flash-lite | 2758 | 730 | $0.002652 | continuation |
| 6 | 12:11:31.341 | Technical feasibility analyst | 3.5-flash-lite | 2243 | 464 | $0.001833 | continuation |
| 7 | 12:11:32.557 | Market evidence analyst | 3.5-flash-lite | 3325 | 850 | $0.003122 | continuation |
| 8 | 12:11:37.943 | Startup validation synthesist | 3.8-flash | 7357 | 881 | $0.008821 | plain |
| 9 | 12:11:42.271 | Validation report writer | 3.8-flash | 5233 | 4138 | $0.019442 | plain |
| 10 | 12:11:53.856 | Guardrail Agent | 3.8-flash | 4102 | 733 | $0.005825 | plain |
| | | **run total** | | 32,959 | 8,896 | **$0.048839** | 34.6 s wall |

### CAN answer

**Cost per agent — but only by reading prompt text, and only for a run you have already
identified by hand.** The roll-up above is real and exact; the Reporter alone is 40% of the
run ($0.019442 of $0.048839, on 4,138 output tokens). What produced it is not a field: it
is a `re.match` on the first line of `input.messages[0].content`, because
`observation.name` is the constant `"LLM Generation"` on all 40 and `trace.name` is the
constant `"OpenRouter Request"`. **Langfuse itself cannot group by agent** — no
`Group by` in the console and no `where` clause in the API can reach inside prompt text.
Evidence: `analysis-validator-run-12-11.json`, `api-traces-all.json`.

**Cost per run — by timestamp clustering, for this dataset only.** A >120 s gap splits the
40 traces into 12 clusters (`analysis-trace-timeline.json`), and cluster 12 is exactly the
ten calls above. This works here because the project is nearly idle. It is **not a method**
— see the CANNOT list.

**Which model served each call, from which provider, at what latency.** Every trace names
provider (`Google` 31 / `Google AI Studio` 9), slug, endpoint id, permaslug, and a
five-stage latency breakdown. This is the richest thing in the dataset.

**Why a run was slow — at call granularity, well.** `latency`, `timeToFirstToken` and
`completionStartTime` are on every GENERATION, and the SPAN separates OpenRouter's routing
from the provider's own service time. In the run above, call 9 (the Reporter) is 11.46 s of
the 34.6 s wall clock, and the 4,138 output tokens say why. What is **not** visible is the
5.4 s between call 7 ending and call 8 starting — that is CrewAI orchestration and tool
execution, and nothing in Langfuse records it, because only LLM calls are traced.

**Which prompt produced a bad output — yes, completely.** Full prompt in, full completion
out, the model's `reasoning`, and the exact `rawRequest` (temperature, `max_tokens`,
`response_format` schema, `reasoning.effort`). This is the strongest capability present.

**Is a truncated response visible — yes, but only in metadata.** Exactly one trace of the
40 has `openrouter.finish_reason: "MAX_TOKENS"`
([`api-trace-E-foreign-max-tokens.json`](../evidence/audit/langfuse/api-trace-E-foreign-max-tokens.json),
trace `9e491d1f614ab648f318c4dad34a84d3`, output ends mid-word: `"…between MW-101 and MW-11"`).
Its `level` is `DEFAULT` and its `statusMessage` is null, exactly like the other 39 — so it
is **invisible to any level- or status-based filter** and findable only by a metadata query.

**Can a tool call's arguments be recovered — yes, but one trace late.** Trace
`a2579573decfda4258eadda1a305571e` (call 3) emits a tool call and its `output.completion`
is `""` with no `tool_calls` field. The query it chose — `{"comments_per_story":20,
"query":"figma react code","story_limit":5}` — appears only in the **next** trace's input,
as the `assistant` message that call 5 was given. So the question *"what did the demand
analyst search for?"* is answerable, but never from the trace of the call that decided it.
Given that query shape is the exact defect this repo has fought
(`CLAUDE.md` §6), that is a sharp limitation. Evidence:
[`api-trace-B-validator-toolcall.json`](../evidence/audit/langfuse/api-trace-B-validator-toolcall.json).

### CANNOT answer

**Which step failed — because no failure is representable.** All 80 observations are
`level: DEFAULT` with `statusMessage: null`; all 40 SPANs are `status_code: 200`. Nothing
in the project is an error, so the rendering of one is **NOT CHECKED — no failing sample
exists**. What *is* checkable: a request that never reaches a provider, or that the app
retries in Python, or that fails guardrail validation, produces **no OpenRouter
chat-completion** and therefore **no trace at all**. The broadcast is emitted per completed
OpenRouter request; a failed LLM call is not visible as a failed trace, it is visible as an
absence, and an absence cannot be counted.

**Whether quality drifts — no instrument exists.** Zero scores, zero score configs, zero
evaluators, zero datasets, zero experiments, zero annotation queues, and no LLM connection
with which to run a judge (§4). The `Scores` panel on Home reads "No data". There is one
day of data, so even a manual trend has nothing to trend against.

**Are two concurrent runs separable — no.** Three independent facts, each measured:

1. **No correlating field exists.** `sessionId`, `userId`, `tags`, `release`, `version`
   and `externalId` are null or empty on **40/40** app traces, and `trace.name` is a
   constant. There is nothing to group by.
2. **Calls within one run already interleave.** 16 overlapping wall-clock pairs exist in
   snapshot 1 (`analysis-trace-timeline.json`); calls 2 and 3 of the run above start 23 ms
   apart and overlap for their whole duration, because the three research branches are
   concurrent by design.
3. So two runs launched together would produce two interleaved sequences of
   `OpenRouter Request` with no field separating them. **Timestamp clustering, the method
   that worked in §5, would silently merge them** and report one run at double the cost.

This is reasoned from field availability, not observed: **only one application run exists
in the entire project**, so a concurrent pair was never available to test. Recorded as an
inference, explicitly.

**Cost per flow, per workflow id, per user, or per deployment — no.** Nothing distinguishes
a Brief Crew call from an Idea Validator call from a builder-graph call except the prompt
text. `run_id`, `workflow_id` and the app's own `session_id` reach Langfuse nowhere.

**Anything about the other 30 traces in this project.** They are not this application —
see §6.2.

---

## 6. Surprises

### 6.1 A second worker wrote into this project **during the audit**, and its probes are the most informative rows in it

The console showed 45 traces where snapshot 1 had 40. The five extra arrived at
`12:54:34–12:54:45Z`, under the `MultiAgentCrewAI` key, named `obs-probe-*` — they are a
sibling worker's deliberate probes of the OpenRouter→Langfuse field mapping, not
application traffic. **They are the only traces in the project that populate `sessionId`,
`userId`, a non-`default` environment, or a custom trace name.** Recorded because they are
now permanently in the data and anyone counting later will hit them, and because what they
demonstrate is directly useful (from their `rawRequest`, in
[`api-traces-recheck.json`](../evidence/audit/langfuse/api-traces-recheck.json)):

| Sent in the OpenRouter request body | Where it lands in Langfuse |
| --- | --- |
| `user: "…"` | `trace.userId` ✅ (via `langfuse.user.id`) |
| `session_id: "…"` | `trace.sessionId` ✅ (via `langfuse.session.id`) |
| `trace.trace_name` | `trace.name` ✅ — overrides `"OpenRouter Request"` |
| `trace.run_id`, and arbitrary keys like `agent_role`, `task_name` | `trace.metadata.<key>` ✅ — queryable |
| `environment` | `trace.environment` ✅ |
| `release` | `trace.metadata.release` only — **`trace.release` stays null** ❌ |
| `tags` | `trace.metadata.tags` only — **`trace.tags` stays `[]`** ❌ |
| `trace.trace_id` | `metadata.resourceAttributes["openrouter.trace.id"]` only — **the Langfuse trace id is still server-assigned** ❌ |

> **CORRECTION (orchestrator, 2026-09-05, after both independent position papers re-checked the evidence).** The row above and the paragraph below it are WRONG. The two traces compared (`8b15b51c…`, `dbd49206…`) sent *different* `trace.trace_id` values and shared only a `run_id` metadata key. Where two probes shared one `trace.trace_id` (`openrouter-forwarding.md` probes d1+d2), Langfuse holds ONE trace, `8b15b51c…`, with 4 observations, and its id equals `sha256(trace_id)[:32]` — recomputed by both analysts. So the broadcast path CAN merge calls into one trace when the caller supplies `trace.trace_id`; what it cannot do is supply that value itself. `AUDIT.md` §4 carries the corrected statement. The original text is left in place so the misreading stays visible.

The last row is the important one: **two requests sharing one `run_id` still produced two
separate traces** (`8b15b51c…` and `dbd49206…`). So the broadcast path cannot make an app
run into a single parent trace; the most it can do is stamp a `run_id` into metadata that
traces can then be *filtered* by. That is a real answer to §5's grouping problem and it
costs no SDK — but it is a change to the request body, which is the codebase worker's area,
not mine.

### 6.2 **Only 10 of the 40 traces are this application.** The project is a shared bucket for three unrelated apps

`openrouter.api_key_name` splits snapshot 1 three ways:

| API key name | Traces | What the prompts are about |
| --- | ---: | --- |
| `WikiSkills` | **16** | Singapore MRT maintenance planning; "Extract a draft maintenance request…" |
| `LTA_ML_PROBLEM` | **14** | The same MRT domain, plus a `"You are a strict evaluation judge"` scoring harness |
| **`MultiAgentCrewAI`** | **10** | **This repository** — Scoper, three analysts, Synthesist, Reporter, Guardrail |

Because the OpenRouter integration is **workspace-level**, it broadcasts every request the
account makes, from every key and every project. So:

- **$0.1839 of total cost, 0.0488 of it is this app — 27%.** Any cost figure read off the
  Langfuse Home dashboard is *the owner's whole OpenRouter account*, not this product.
  The console offers no filter that would separate them, because `api_key_name` lives in
  metadata rather than in a first-class field.
- The `metrics/daily` split by model is likewise cross-app: `gemini-3.8-flash`'s 125,406
  tokens are mostly the two MRT applications.
- The only surviving separator is a metadata query on `openrouter.api_key_name` — which
  works, and which nothing currently uses.

### 6.3 The one full run is legible end to end, and that is genuinely good

Notwithstanding everything above: the ten calls of the `12:11` run reconstruct into the
exact pipeline `.agent`/`CLAUDE.md` §3 describes — Scoper on the escalation tier, three
concurrent cheap-tier branch agents each taking two turns around one tool call, Synthesist,
Reporter, and a CrewAI `Guardrail Agent` validating the report. Every prompt, every tool
result, every score in the rendered report, and the model's own reasoning are all present
verbatim. The data that would answer "why did this run say `REJECT / FLOOR_NO_MARKET`" is
all there. What is missing is not depth — it is **identity and aggregation**.

### 6.4 Smaller things worth knowing

- **`CLAUDE.md` says OpenRouter's per-generation cost "never reaches the process."** It
  reaches *Langfuse*: `gen_ai.response.id` is on every trace, so
  `mcp__openrouter__get-generation` could reconcile the estimate against OpenRouter's own
  billing for any of these 40 calls. That is the missing capture item 41 asks for, already
  present on this side of the wall.
- **The console's default Tracing table lists observations, not traces** ("Total ≈ 93"),
  while Home says 45 traces. Two correct numbers that look like a contradiction.
- **The `metrics/daily` endpoint used for the cost figures is deprecated** — it returns a
  `_deprecation` block naming a **sunset of 2026-11-16** and directs callers to
  `GET /api/public/v2/metrics`. Anything built on it now has a ten-week shelf life.
  Evidence: `api-surfaces.json`.
- **`/api/public/dataset-run-items` answers 400**, not an empty list, when called without
  required params — the only non-200 among sixteen probed endpoints.
- The console renders timestamps in **local time (UTC+8)** while the API returns UTC. The
  `12:11:53Z` trace reads `20:11:53` on screen; the two are the same row.
- `openrouter.entity_id` and `openrouter.creator_user_id` (identical, constant across all
  45 traces) are an OpenRouter **account** identifier. Not a credential, but it is present
  in the exported JSON in this evidence tree — worth knowing before that tree is shared.

---

## 7. Not checked, and why

- **How Langfuse renders an error trace** — no observation in the project has
  `level != DEFAULT`, so there is no sample. Would need a deliberately failed call.
- **Whether ingested cost beats computed cost** — the two are numerically identical for
  both models in use (§3), so this dataset cannot discriminate. Would need a model whose
  Langfuse definition price differs from OpenRouter's.
- **Whether two concurrent app runs are separable in practice** — only one application run
  exists (§5). Answered by inference from field availability, and labelled as such.
- **Data older than 2026-09-05** — none exists; `metrics/daily` returns a single day.
- **Retention, ingestion limits and plan quotas on the Hobby tier** — visible under
  Settings → Billing, which was not opened; billing is outside this audit's scope.
- **`GET /api/public/v2/metrics`** — the replacement for the deprecated daily endpoint was
  not exercised; the deprecated one still answers and its figures agree with the console.

---

## 8. Files written

**Inventory:** `docs/observability/audit/langfuse-inventory.md` (this file)

**Evidence:** `docs/observability/evidence/audit/langfuse/`

| File | What it is |
| --- | --- |
| `api-traces-all.json` | Snapshot 1 — all 40 traces, full JSON, with input/output/metadata |
| `api-traces-recheck.json` | Snapshot 2 — all 45 traces, showing the 5 probe rows |
| `api-observations-all.json` | All 80 observations (40 GENERATION + 40 SPAN) |
| `api-surfaces.json` | Raw response from 16 API endpoints — sessions, scores, prompts, datasets, comments, annotation queues, metrics/daily, projects, … |
| `api-models-all.json` | All 182 Langfuse model definitions, both pages |
| `api-trace-A-validator-scoper.json` | Rep. 1 — first call of the one full app run |
| `api-trace-B-validator-toolcall.json` | Rep. 2 — the empty-output tool-call turn |
| `api-trace-C-validator-reporter.json` | Rep. 3 — largest token count in the project |
| `api-trace-D-validator-guardrail.json` | Rep. 4 — most recent app trace |
| `api-trace-E-foreign-max-tokens.json` | Rep. 5 — the only `MAX_TOKENS` finish reason |
| `analysis-trace-timeline.json` | Derived: all 40 in time order with role, tokens, cost, overlap inputs |
| `analysis-validator-run-12-11.json` | Derived: the ten-call run of §5, per-agent |
| [console-01](../evidence/audit/langfuse/console-01-traces-list-loading.jpg) … [console-19](../evidence/audit/langfuse/console-19-playground-no-model.jpg) (`.jpg`) | Console captures: traces list, trace detail (tree / output / metadata), Sessions, Users, Scores, Prompts, Datasets, Home, Evaluators, Dashboards, Human Annotation, Settings→Models, Settings→Integrations, Experiments, Alerts, Playground |
