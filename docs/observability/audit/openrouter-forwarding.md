# OpenRouter → Langfuse: what is configured, and what can actually cross

**Audited 2026-09-05** against the live OpenRouter account and Langfuse project
`cmto3mj7t06ykad0ipon3ksbw` at `https://us.cloud.langfuse.com`. Nothing was
changed: this is a record of the prior state plus seven live probes.

Every claim below names a file under
[`../evidence/audit/openrouter/`](../evidence/audit/openrouter/). Where a claim
is an inference rather than a measurement it says **NOT VERIFIED** and why.

No key value appears in this document or in any evidence file. The two
screenshots of the destination editor show the credential inputs as dots,
which is how OpenRouter renders them; the management API returns them
pre-masked, and the masks were redacted again before the JSON was written.

---

## 1. Prior configuration, exact

There is **one** broadcast destination and it is the only thing feeding the
Langfuse project. Read from the management API — the authoritative form, since
the UI renders a summary — and corroborated against the editor screen.

Evidence: [`part1-destinations-api.json`](../evidence/audit/openrouter/part1-destinations-api.json),
[`part1-observability-settings-page.jpg`](../evidence/audit/openrouter/part1-observability-settings-page.jpg),
[`part1-destination-edit-connection.jpg`](../evidence/audit/openrouter/part1-destination-edit-connection.jpg),
[`part1-destination-edit-regions-metadata-privacy.jpg`](../evidence/audit/openrouter/part1-destination-edit-regions-metadata-privacy.jpg),
[`part1-destination-edit-sampling-keyfilter-rules.jpg`](../evidence/audit/openrouter/part1-destination-edit-sampling-keyfilter-rules.jpg).

| Setting | Value |
| --- | --- |
| Feature master switch | **Broadcast: ON** (page toggle, green) |
| Sibling feature | **Input & Output Logging: ON** (Beta) — OpenRouter's own log store, separate from broadcast |
| Destinations configured | **1** (`total_count: 1`) |
| Type | `langfuse` |
| Destination id (API) | `8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b` |
| Destination id (UI route) | `15910` |
| Workspace | `d9782653-59a8-51a5-9ff4-b28da297b63f` ("Default Workspace") |
| Name | `multi-agent-crew-ai` |
| `enabled` | `true` |
| Langfuse host | `https://us.cloud.langfuse.com` |
| Public key prefix shown | `pk-l…` — the API returns it already masked to 11 characters; nothing beyond `pk-l` is legible anywhere |
| Secret key | masked, 11 characters, never rendered |
| Custom headers | none (placeholder text only) |
| **Regions** | **Global ✅ · European Union ☐ · United States ☐** — only traffic to `https://openrouter.ai` is forwarded |
| **Privacy Mode** | **☐ OFF** → prompts and completions **are** sent |
| **Additional generation metadata → Cost (15 fields)** | **☐ OFF** (`broadcast_generation_cost: false`) |
| **Additional generation metadata → Identity (18 fields)** | **☐ OFF** (`broadcast_generation_identity: false`) |
| **Additional generation metadata → Request context (19 fields)** | **☐ OFF** (`broadcast_generation_request_context: false`) |
| Sampling rate | `1` (100%) |
| Included API keys | none selected |
| Excluded API keys | none selected |
| `api_key_hashes` | `null` — the API documents this as "all keys" |
| `filter_rules` | `null` — "No filter rules configured. All traces will be sent" |
| Created / updated | `2026-09-05T08:24:27.107Z` / `2026-09-05T08:24:50.201Z` |

The destination row's own menu offers **Edit · Status · Send Trace · Disable ·
Delete**; `Send Trace` is a manual test emitter and was not pressed.

The editor's own wording on the Identity category is worth quoting, because it
is a privacy fact the Privacy Mode row does not tell you:

> Identity (18 fields) — Application, API key, user, origin, and request
> identity fields. **Privacy mode does not remove these identity fields when
> enabled.**

### The integration is per-workspace, and the project is not this app's alone

Evidence: [`part1-api-key-inventory.json`](../evidence/audit/openrouter/part1-api-key-inventory.json),
[`part3-langfuse-24h-survey.json`](../evidence/audit/openrouter/part3-langfuse-24h-survey.json).

The account holds **13 API keys**. This application uses the one named
**`MultiAgentCrewAI`** — confirmed, not assumed: every probe trace carries
`metadata["openrouter.api_key_name"] = "MultiAgentCrewAI"`.

Because `api_key_hashes` is `null`, the destination is scoped to the
**workspace**, not to a key. A per-key restriction exists (Included / Excluded
API Keys) and is unset. The measured consequence, over the 24 hours to
`2026-09-05T13:01Z`:

```text
45 traces in the Langfuse project, from THREE OpenRouter keys:
  MultiAgentCrewAI  15      (this application)
  LTA_ML_PROBLEM    14      (unrelated)
  WikiSkills        16      (unrelated)
models: google/gemini-3.8-flash 34, google/gemini-3.5-flash-lite 11
```

**Two thirds of the Langfuse project is not this application**, and nothing on
the OpenRouter side distinguishes them except that one metadata key. This is a
finding for whoever owns the Langfuse console inventory, and the fix is one
field on this destination.

### OpenRouter's own ledger, for Task 3's reconciliation

Evidence: [`part1-openrouter-logs-generations.jpg`](../evidence/audit/openrouter/part1-openrouter-logs-generations.jpg).

`https://openrouter.ai/activity` is an **aggregate dashboard**, not a ledger:
tabs Overview / Trends / Explore / Guardrails, cards for Total spend, Requests,
Token volume, Cache hit rate, Blended $/1M, and Top API Keys / Top Apps lists.
It answers "how much", never "which request".

The per-request ledger is **`https://openrouter.ai/logs`**, tabs
**Generations · Upstream Requests · Sessions · Videos · Batches**, with a time
filter (Past 24 Hours by default) and a column picker. The Generations table
columns as rendered are:

```text
Date | Model | Provider | App | Input | Output | Cost | Credit…
```

The generation id is not a visible column; it is reachable per row and through
`GET /api/v1/generation?id=…`. `App` is the `X-Title` / `HTTP-Referer`
attribution and reads `Unknown` when neither header is sent — which is what
this repository sends today.

The `Sessions` tab means OpenRouter tracks `session_id` on its own side as well
as forwarding it.

---

## 2. What the docs say, quoted

Sources, saved verbatim as markdown under
[`../evidence/audit/openrouter/docs/`](../evidence/audit/openrouter/docs/):

- `https://openrouter.ai/docs/guides/features/broadcast` → `docs/broadcast-overview.md`
- `https://openrouter.ai/docs/guides/features/broadcast/langfuse` → `docs/broadcast-langfuse.md`
- `https://openrouter.ai/docs/guides/features/input-output-logging` → `docs/input-output-logging.md`

**The `trace` object and its Langfuse mapping** (broadcast/langfuse):

| Key | Langfuse Mapping (doc's own words) |
| --- | --- |
| `trace_id` | Trace ID — "Group multiple requests into a single trace" |
| `trace_name` | Trace Name — "Custom name displayed in the Langfuse trace list" |
| `span_name` | Span Name — "Name for intermediate spans in the hierarchy" |
| `generation_name` | Generation Name — "Name for the LLM generation observation" |
| `parent_span_id` | Parent Observation ID — "Link to an existing span in your trace hierarchy" |
| `environment` | Environment — "Populates the first-class `Environment` field used by the Langfuse project filter" |
| `release` | Release — "Application release/version associated with the trace" |

> "The `user` field maps to Langfuse's User ID for user-level analytics"
> · "The `session_id` field maps to Langfuse's Session ID for grouping
> conversations" · "Any additional keys in `trace` are passed as trace metadata
> and can be used for filtering and analysis in Langfuse"
> — broadcast/langfuse, *Additional Context*

**Tags are not in that table.** The overview's destination index describes
LangSmith, Datadog and Braintrust as supporting tags and describes Langfuse as
"Supports trace naming, user/session IDs, and arbitrary metadata" — no tags.

**Linking to your own tracing** (broadcast overview, *Linking to External Traces*):

> "If you have your own tracing instrumentation (e.g., OpenTelemetry), you can
> use `parent_span_id` to nest OpenRouter calls under your existing spans"

with the worked example passing `trace_id: "your-existing-trace-id"` and
`parent_span_id: "your-existing-span-id"`. **The docs do not say how a
caller-supplied `trace_id` string becomes a Langfuse trace id** — that gap is
what §3 closes by measurement.

**What is always in a trace** (broadcast overview, *Trace Data*):

> "Request & Response Data: The input messages and model output (with
> multimodal content stripped for efficiency) · Token Usage · Cost Information:
> The total cost of the request · Timing · Model Information: The model slug
> and provider name · **Tool Usage: Whether tools were included in the request
> and if tool calls were made**"

**Content is configurable, per destination** (*Privacy Mode*):

> "When Privacy Mode is enabled, the following data is stripped before sending
> traces: Input messages (prompts sent to the model), Output choices
> (completions returned by the model). All other trace data … is still sent
> normally."

**Latency and ordering** (*Security*):

> "Traces are sent **asynchronously after requests complete**, so enabling
> broadcast does not add latency to your API responses."

"After requests complete" is the ordering guarantee and the whole of it: there
is no start-of-request emission and **no stated delivery-time bound**. For
regional endpoints the overview adds that "Delivery is best-effort" and that a
failed regional delivery "is not retried through the global retry queue the way
global traffic is" — implying global traffic **is** retried through a queue.
No SLA, no ordering guarantee between traces, is documented anywhere.

**Sampling** is per destination, and:

> "Sampling is deterministic: when you provide a `session_id`, all traces within
> that session will be consistently included or excluded together."

**Failed requests: the docs say nothing.** Neither page states whether a 4xx,
a 5xx or a provider error is forwarded. Measured in §3.

**Streaming: the docs say nothing either.** Measured in §3.

**Cost** is described only as "The total cost of the request" — the docs do not
say whether the destination shows OpenRouter's figure or the platform's own
price table. Measured in §3.

---

## 3. What the probes proved

Seven requests to `POST https://openrouter.ai/api/v1/chat/completions`, model
`google/gemini-3.5-flash-lite:nitro` (`CHEAP_MODEL` from `config.py` with the
`openrouter/` prefix stripped), `max_tokens: 8`, one marker word as the prompt.
Sent `2026-09-05T12:54:34Z`–`12:54:45Z`; Langfuse read back at `12:57`–`13:01Z`.

Evidence:
[`part3-probe-requests-and-responses.json`](../evidence/audit/openrouter/part3-probe-requests-and-responses.json) (every request body and response),
[`part3-langfuse-traces.json`](../evidence/audit/openrouter/part3-langfuse-traces.json) (every trace and observation Langfuse returned),
[`part3-field-mapping.json`](../evidence/audit/openrouter/part3-field-mapping.json) (the table below, machine-readable),
[`part3-openrouter-generation-records.json`](../evidence/audit/openrouter/part3-openrouter-generation-records.json),
[`part3-langfuse-console-trace-d-tree.jpg`](../evidence/audit/openrouter/part3-langfuse-console-trace-d-tree.jpg),
[`part3-langfuse-console-trace-d-metadata.jpg`](../evidence/audit/openrouter/part3-langfuse-console-trace-d-metadata.jpg).

Six successful calls produced **five** traces, because d1 and d2 merged.

### The table

| Sent | Where it appeared in Langfuse | Verdict |
| --- | --- | --- |
| `trace.trace_id` | the trace's **id**; two requests sharing it merged into one trace holding both generations | **arrived** |
| `trace.trace_name` | `trace.name` (default `OpenRouter Request`) | **arrived** |
| `trace.generation_name` | `observation.name` on the GENERATION (default `LLM Generation`) | **arrived** |
| `trace.span_name` | *nothing.* No span of that name exists; the string survives only inside the echoed `output.rawRequest` | **did not arrive — contradicts the doc** |
| `trace.parent_span_id` | `observation.parentObservationId`, verbatim (`0123456789abcdef`) | **arrived** |
| `trace.environment` | first-class `trace.environment` **and** `observation.environment`, plus `metadata.environment` and `resourceAttributes["langfuse.environment"]` | **arrived** |
| `trace.release` | observation-level Release chip, `metadata.release`, `attributes["langfuse.release"]`, `resourceAttributes["langfuse.release"]` — but the API's `trace.release` is `null` | **arrived, observation-level only** |
| `trace.run_id` (arbitrary) | `observation.metadata.run_id` and `trace.metadata.run_id` | **arrived** |
| `trace.agent_role` (arbitrary) | `observation.metadata.agent_role` = `"Market evidence analyst"` | **arrived** |
| `trace.task_name` (arbitrary) | `observation.metadata.task_name` = `"market_task"` | **arrived** |
| `trace.tags` | `metadata.tags` — an ordinary metadata key. `trace.tags` stayed `[]` | **arrived as metadata, not as tags** |
| top-level `tags` | *nothing.* Only inside the echoed `output.rawRequest.tags` | **did not arrive** |
| top-level `user` | `trace.userId`, `attributes["langfuse.user.id"]`, `metadata["openrouter.user_id"]` | **arrived** |
| top-level `session_id` | `trace.sessionId`, `attributes["langfuse.session.id"]` | **arrived** |
| header `X-Title` | *nothing in Langfuse* — but it **did** land in OpenRouter's own Logs `App` column while every sibling probe reads `Unknown` | **did not arrive (config-dependent)** |
| header `HTTP-Referer` | *nothing in Langfuse* | **did not arrive (config-dependent)** |
| `stream: true` | a complete trace, 3 observations, input/output/usage/cost all present | **arrived** |
| invalid model id → HTTP 400 | *nothing.* No trace, no observation, no error record | **did not arrive** |

Probe b is the cleanest control in the set: the same marker reached OpenRouter
(visible in the App column of the Logs screenshot) and did not reach Langfuse.
That separates "OpenRouter never saw it" from "OpenRouter saw it and did not
forward it", and it is the second of the two.

### The id derivation — measured, and the most useful thing here

The docs never say it. Eight of eight exact matches:

```text
Langfuse trace id       = sha256(trace.trace_id  or  <openrouter generation id>).hexdigest()[:32]
Langfuse generation id  = sha256(<openrouter generation id>).hexdigest()[:16]

sha256("obsprobe-trace-1788612874")[:32]        == 8b15b51c4f6c36711f217e68ad5c99ac   ✓
sha256("obsprobe-stream-1788612874")[:32]       == dbd49206c2c8a478fcf97ce967645760   ✓
sha256("gen-1788612875-1qJQ41IafHPo6WUnyTtZ")[:32] == 7bb1830b2921c9336483b844723fccfd ✓
sha256("gen-1788612880-8wpoqatoJCppvLlOOwVy")[:16] == bfdd7a538241b627                ✓   (+4 more)
```

These are OpenTelemetry ids — 16-byte trace, 8-byte span — derived
deterministically from a string. **The application can compute either value
off-line, without calling OpenRouter**, which is what makes §4's joining answer
a yes rather than a maybe.

### The trace a plain call produces

```text
trace.name       "OpenRouter Request"
trace.id         sha256(generation id)[:32]
observations     2 - GENERATION "LLM Generation"
                     └─ SPAN "provider attempt 1: Google"
input            {"messages":[{"role":"user","content":"obsprobe-a-…"}]}
output           {"completion":"…", "reasoning":null, "rawRequest":{…the whole body…}}
environment      "default"       userId/sessionId/tags   null / null / []
totalCost        1.48e-05
```

A streaming call adds a third observation, a span named `generation`.

Metadata present on every trace **without being asked for**, with all three
"Additional generation metadata" categories switched off:

- identity-ish: `openrouter.api_key_name`, `openrouter.entity_id`,
  `openrouter.creator_user_id`, `openrouter.user_id`
- timing: `router_latency_ms`, `provider_request_ms`, `provider_headers_ms`,
  `first_token_ms`, `provider_body_end_ms`, `provider_time_to_first_token_ms`
- routing: `provider_name`, `provider_slug`, `finish_reason`, and
  `provider_responses[]` — `{id, provider_name, status, latency, is_byok,
  endpoint_id, model_permaslug}`
- pricing: `input_unit_price`, `output_unit_price`, and
  `gen_ai.usage.{input,output,total}_cost`
- usage: input/output/total tokens plus `cached`, `audio`, `video`,
  `reasoning`, `image` breakdowns

So the three opt-in categories add fields **beyond** a payload that is already
detailed. What they add was not enumerated, because enumerating it means
enabling them, and this task changes nothing — **NOT VERIFIED: the exact 15/18/19
fields each category adds.** The Identity description names "Application …
and origin", which is where `X-Title` and `HTTP-Referer` most plausibly live,
but that is an inference from a label. **NOT VERIFIED: that enabling Identity
would carry `X-Title` to Langfuse.**

### Cost is OpenRouter's own figure, to the last digit

`GET /api/v1/generation?id=…`.`total_cost` against the Langfuse observation's
`calculatedTotalCost`, six for six:

| probe | OpenRouter | Langfuse | equal |
| --- | --- | --- | --- |
| a, b, c, f | `1.48e-05` | `1.48e-05` | yes |
| d1, d2 | `1.51e-05` | `1.51e-05` | yes |

The figure rides on the span as `gen_ai.usage.input_cost` / `output_cost` /
`total_cost`, so **Langfuse's own model price table is not consulted** for these
observations. That matters here for a specific reason: `CHEAP_MODEL` carries
`:nitro`, and `gen_ai.request.model` records `google/gemini-3.5-flash-lite`
**without** the suffix while `output.rawRequest.model` keeps it. A price table
keyed on the model slug would have priced a `:nitro` route at the published
floor; OpenRouter's own number does not, and it is the number Langfuse shows.

### One thing nobody asked for: the whole request body is echoed

`trace.output.rawRequest` is the caller's **entire** JSON body, verbatim —
`model`, `max_tokens`, `user`, `session_id`, `tags`, the whole `trace` object,
and OpenRouter's own `_skin: "chat-completions"`. That is how the fields that
"did not arrive" are still findable in the trace JSON, and it is why the table
above distinguishes *arrived as a field* from *present in the echo*. It is also
a disclosure surface: anything the application ever puts in a request body
reaches Langfuse while `privacy_mode` is off, whether or not OpenRouter maps it.

---

## 4. The settled answers

**Can a run identifier reach Langfuse through OpenRouter at all, and by what
mechanism?** — **Yes, by three different mechanisms, and they are not
equivalent.**

1. `trace.trace_id` — makes the run identifier *the trace itself*. Every call
   sharing it collapses into one Langfuse trace. Measured: d1 and d2 became one
   trace with two generations.
2. `session_id` (top level, or the `x-session-id` header) — makes it a Langfuse
   **Session**, which groups traces without merging them, and which also fixes
   sampling to include or exclude the whole run together.
3. `trace.run_id` (or any arbitrary key) — a plain metadata field, filterable in
   Langfuse, on both trace and observation.

For a CrewAI run these answer different questions. `trace_id` gives one trace
per run and is the right choice if the run is the unit of analysis;
`session_id` keeps one trace per LLM call and groups them, which is closer to
how the console already thinks. Both can be sent at once, and were.

**Can an agent role / task name reach it?** — **Yes.** `trace.agent_role` and
`trace.task_name` arrived intact as observation metadata, verbatim strings
including spaces (`"Market evidence analyst"`). Any key inside `trace` that is
not one of the seven reserved names becomes metadata. There is no length or
count limit documented, and none was probed. **NOT VERIFIED: the size ceiling
on the `trace` object.**

**Can a trace id or parent be set so app-side observations and OpenRouter
generations share one trace?** — **Yes, and both halves work.**

- The trace id is `sha256(your string)[:32]`, so a Langfuse SDK in the app can
  compute the identical id and write its own spans into the same trace.
- `parent_span_id` is stored verbatim as `parentObservationId`. In the probe it
  pointed at `0123456789abcdef`, an observation that does not exist, and
  Langfuse tolerated it — the generation simply rendered at the trace root. If
  the app had actually written a span with that id, the OpenRouter generation
  would nest beneath it.

The practical shape is therefore: the app owns a span, passes
`trace: {trace_id: <run id>, parent_span_id: <its own span id>}`, and the
OpenRouter generation lands inside the app's own hierarchy. **NOT VERIFIED
end to end** — no app-side span was written in this audit, because the app has
no Langfuse SDK and installing one is another worker's surface. What is
verified is every ingredient: the id function, the verbatim parent, and the
merging.

One caveat the docs get wrong and the probe caught: **`span_name` does not
create the intermediate span the documentation promises.** The doc's worked
example claims `Pipeline (trace) → Summarization Step (span) → Generate Summary
(generation)`; what arrives is `trace → generation`, with `span_name` visible
only in the echoed body. Any grouping level between trace and generation has to
come from the app writing it, not from this field.

**Are failures forwarded?** — **A request OpenRouter itself refuses is not.**
Probe e (`"openrouter/this-model-does-not-exist-obsprobe is not a valid model
ID"`, HTTP 400) produced no generation id, no trace, no observation and no
error record. There is no negative-space entry anywhere: from Langfuse the
request simply never happened.

**NOT VERIFIED: a request that reaches a provider and then fails** — a provider
5xx, a timeout, a content filter, an exhausted retry. Probe e died at
OpenRouter's own validation layer, before routing, so it does not settle the
case. The trace schema has obvious room for it — every trace carries
`provider_responses[]` with a per-attempt `status`, and the spans are named
`provider attempt 1: Google` — which suggests attempts and their statuses are
modelled. That is a reading of a field name, not a measurement. Forcing a
provider error was out of scope for a $0.05 probe budget on one cheap model.

**Is content forwarded, and is it configurable?** — **Forwarded today; one
checkbox from not being.** `privacy_mode` is `false`, so `trace.input` carries
the full messages array and `trace.output` carries the completion *and the
entire request body*. Turning Privacy Mode on strips input messages and output
choices per the docs, keeps everything else, and — per the editor's own
warning — does **not** strip the Identity fields. It is a per-destination
switch, so a second destination could take metrics-only traces while this one
keeps content.

---

## 5. What OpenRouter structurally cannot know

Not a limitation of the configuration: a limitation of where OpenRouter sits.
It sees one HTTP request/response pair at a time and nothing else. Each of
these is argued from the evidence above.

**Agent and task boundaries.** In the probe traces, `agent_role` and
`task_name` are present *only* because I typed them into the request body.
Every trace that did not carry them — the three plain probes, and all 30
traces in the 24h survey from the other two API keys — has no notion of an
agent at all. OpenRouter cannot infer that two calls belong to the same
CrewAI task, because nothing in an OpenAI-schema request says so.

**Tool calls as executions.** The docs promise "Tool Usage: whether tools were
included in the request and if tool calls were made" — that is the model
*asking*. The tool actually running is a function call inside this process:
Firecrawl, the HN Algolia fetch, the GitHub search. OpenRouter is not in that
path and no HTTP request reaches it, so the tool's arguments, its result, its
latency, its failure and its retries are all invisible. This repository's
tool envelopes — `status`, `query`, `result_count`, `notes` — exist entirely
outside anything OpenRouter can see.

**Retries as a concept.** OpenRouter models *its own* provider retries:
`provider attempt 1: Google` is a span, and `provider_responses[]` is an array.
It has no representation of the retries this system actually cares about — a
CrewAI guardrail retry, a `guardrail_max_retries` regeneration, an agent loop
iteration. Each of those is a *fresh* request, so it arrives as a fresh trace
with a fresh generation id, unrelated to the one before it. The probe proves
the only fix available: the two d-probes were separate requests and became one
trace *because I supplied `trace_id`*. Without a caller-supplied identifier,
five guardrail attempts are five unrelated traces.

**Cancellation.** This system cancels at the next CrewAI `PRE_STEP` boundary,
which is between calls. An in-flight OpenRouter request either completes
(forwarded, indistinguishable from a wanted one) or is abandoned client-side.
Probe e establishes that a request producing no completion produces no trace;
there is no cancelled state to forward.

**Run start and end.** Traces are sent "asynchronously after requests complete".
There is no start event and no end event, so a run that opens, pauses at a
human gate for an hour and resumes has no representation of its own duration —
only a scatter of completed generations. A gate waiting on a person emits
nothing at all, because nothing is being asked of a model.

**Everything that is not an LLM call.** The 24h survey returned 45 traces and
every one is a chat completion. OpenRouter's own Logs page, over the same
window, shows `Gemini Embedding 2` generations that have **no** counterpart in
Langfuse. Embeddings, rerank and Firecrawl raise no chat-completion event, so
they are absent from the traces and absent from the cost total — the same blind
spot `builder/budget.py` already documents for the static estimate, arriving
here from the other direction. *(This is measured on generations another
workload produced, not on a probe of my own — the budget confines probes to the
cheap chat model. **NOT VERIFIED by direct probe: that an embeddings request is
never forwarded.**)*

**And the converse, which is the sharper risk.** OpenRouter cannot tell this
application's traffic from any other traffic on the workspace, so the Langfuse
project holds all of it. Two thirds of the last 24 hours is not this app.

---

## 6. Probe cost

Evidence: [`part3-openrouter-generation-records.json`](../evidence/audit/openrouter/part3-openrouter-generation-records.json).

**7 calls sent · 6 billable generations · $0.0000894 total**, from OpenRouter's
own `GET /api/v1/generation?id=…` records, not estimated:

| probe | generation id | tokens in/out | `total_cost` |
| --- | --- | --- | --- |
| a | `gen-1788612875-1qJQ41IafHPo6WUnyTtZ` | 16 / 4 | `$0.0000148` |
| b | `gen-1788612877-6twjdYtfRyDna6jxINoG` | 16 / 4 | `$0.0000148` |
| c | `gen-1788612878-oTc3QVmsoeEkV5BSEscd` | 16 / 4 | `$0.0000148` |
| d1 | `gen-1788612880-8wpoqatoJCppvLlOOwVy` | 17 / 4 | `$0.0000151` |
| d2 | `gen-1788612882-VIwPVS3nYy8r0FBUH6Xi` | 17 / 4 | `$0.0000151` |
| e | — (400, no generation) | — | `$0` |
| f | `gen-1788612885-hFm6Av9rEF3NMfxjJXWk` | 16 / 4 | `$0.0000148` |
| | | | **`$0.0000894`** |

Against the $0.05 authorisation: **0.18% used**. All seven on
`google/gemini-3.5-flash-lite:nitro`, `max_tokens: 8`, served by Google Vertex.

---

## Appendix: things a later task will want, stated plainly

- Nothing was changed. The §1 table is the baseline to diff against.
- The trace-id function is `sha256(s).hexdigest()[:32]`; the observation-id
  function is `sha256(generation_id).hexdigest()[:16]`. Both were verified on
  eight cases and neither is documented, so re-verify before depending on it —
  it is an implementation detail OpenRouter has not promised to keep.
- The four fields worth sending from this codebase, in order of value:
  `trace.trace_id` = the run id, `trace.parent_span_id` = the app's own span,
  `trace.agent_role`, `trace.task_name`. All four are proven to arrive.
  `tags` is not worth sending: neither spelling becomes a Langfuse tag.
- Probe markers all contain `1788612874` and the traces are still in the
  project; they are cheap to delete and easy to find.
