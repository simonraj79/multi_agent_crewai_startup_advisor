# Position B — the layer question, argued from the hypothesis REPLACE

**Analyst B, 2026-09-05**, against `main` = `b65bd65`, the three Task 1
inventories and the evidence tree. Position A was not read; I built nothing.

## 0. What I re-measured rather than taking from a summary

- **`trace.trace_id` does become the Langfuse trace id, and two calls sharing it
  merge.** `part3-langfuse-traces.json` →
  `traces["probe-d1 + probe-d2 (shared trace.trace_id)"]`: **one** trace
  `8b15b51c4f6c36711f217e68ad5c99ac`, **4** observations (2 GENERATION + 2 SPAN);
  `sha256(b"obsprobe-trace-1788612874").hexdigest()[:32]` equals it.
- **`GET /api/v1/generation` is fast, durable and rich.** Called on 5 probe ids
  ~19 h old: **5/5 HTTP 200**, **410 / 428 / 478 / 543 / 835 ms** (median 478),
  no rate-limit headers. Fields include `total_cost`, `native_tokens_reasoning`,
  `native_tokens_cached`, `provider_responses[]`, `provider_name`, `latency`,
  `native_finish_reason`, `cache_discount`.
- **The app's TOKEN frame drops the reasoning/cached split.**
  `crewai/.../openai/completion.py:2731-2741` *does* emit `cached_prompt_tokens`
  / `reasoning_tokens`, but `serializer.py:83-99` (`_USAGE_ALIASES`) and
  `:165-192` (`normalize_usage`) return five keys and neither family is among
  them, so `serializer.py:528` carries only prompt/completion/total.
- **langfuse 4.15.1 sets an end time but not a start time.** `span.py:215` —
  `end(*, end_time)`; `client.py:660-676` — `start_observation(...)` has
  `completion_start_time` and **no** `start_time`; `span.py:637-652` —
  `update(...)` takes `usage_details` / `cost_details` before end.

**The two inventories contradict each other and the evidence settles it.**
`langfuse-inventory.md` §6.1 says the Langfuse trace id "is still
server-assigned" and that "two requests sharing one `run_id` still produced two
separate traces". Its two cited ids are `8b15b51c…` (the d-probe *pair*) and
`dbd49206…` (the *stream* probe) — two different `trace_id` strings, not one
shared one; `openrouter-forwarding.md` §3 is right. That mistake was made the day
the derivation was measured, by a careful analyst with the file open: a design
standing on an undocumented sha256 prefix stands on something already misread.

## 1. What REPLACE loses — three items, and one measurement collapses it to one

The honest list: **(a)** true billed cost, **(b)** the provider-attempt span and
upstream provider identity, **(c)** the `rawRequest` echo. **(c) is not a loss:**
`trace.output.rawRequest` is the caller's entire request body verbatim — model,
`max_tokens`, the full `response_format` schema, `tools`, every key the app puts
on the wire (`openrouter-forwarding.md` §3) — and DoD §5.3 sets content capture
default OFF while E3 tests for its absence. Losing it is a gain.

**(a) and (b) are recovered by one call.** `GET /api/v1/generation?id=<response_id>`
returns `total_cost` — measured equal to Langfuse's `calculatedTotalCost` six
times for six (`openrouter-forwarding.md` §3) — *and* `provider_responses`, read
back verbatim: `[{"endpoint_id":"fe0e0167-…","is_byok":false,"latency":814,
"model_permaslug":"google/gemini-3.5-flash-lite-20260721","provider_name":"Google",
"status":200}]`. That is the provider-attempt span's entire content, and an
app-side exporter can render it as a child SPAN *under the app's own node* —
which the broadcast cannot, because `span_name` provably does not create an
intermediate span (`openrouter-forwarding.md` §3, row 4). The app already holds
the key: `serializer.py:525` puts `"response_id": event.response_id` on every LLM
`after` frame, on both the blocking and streaming paths (`app-surface.md` §3.3),
and `config.py:1086-1089` names this exact use.

**Is the per-call fetch viable?** Median 478 ms, off the run's thread. The
nearest documented bucket is the Data API's **30 req/min per key, 500/day per
account** — a *different* endpoint's page, so **NOT VERIFIED for `/generation`**;
design as if it binds. The one full app run in the project is 10 LLM calls, so
30/min tolerates ~3 concurrent runs and 500/day ~50 — fine here, not for a busy
app.

Lazy UPDATE: **no, and it is not needed.** An ended OTel span cannot be modified
and this SDK exposes no post-end update — but `start_observation()` has no
`start_time` while `end(end_time=<ns>)` is explicit, so the shape is forced and
convenient: **open on the `before` frame, `update(cost_details=…)` on the
`after`/TOKEN frame, hold the span open across the fetch, end with the frame's
own timestamp.** The fetch then costs *zero* reported latency, and it forces a
prompt drain — a batched flush would stamp every start at the flush moment and
blow **B4**. On failure or 404, end with the estimate and stamp `cost_source`.

**Why the estimate alone will not do.** `config.py:2390-2399` records eight
endpoints for `gemini-3.5-flash-lite` from `$0.15/$1.25` to `$0.54/$4.50`;
`NITRO_PRICE_FACTOR = 1.8` is that spread's top and `:2396-2398` says it is
*deliberately not applied inside* `compute_cost_usd`, while `:161-166` records
measured dearest-endpoint ratios of **1.0x to 9.5x**. Every `:nitro` cheap-tier
figure is therefore the published floor — and this project has already shipped
`cost_usd = 0.0` over 128,069 real tokens once.

## 2. What REPLACE gains

1. **DoD §5.5 becomes structural.** "Exactly one emits the GENERATION" holds
   because there is one emitter. Under SUPPLEMENT it holds only while a
   `parent_span_id` handshake survives an undocumented derivation, an unbounded
   delivery time (no SLA, `openrouter-forwarding.md` §2), and an ingestion that
   silently accepted a `parentObservationId` pointing at nothing (probe d1).
2. **Failures exist at all.** Probe e (HTTP 400) produced no trace, no
   observation, no error record; **B3, D1, D2, D6** are failure rows and the
   OpenRouter answer to each is an absence. The app has five error surfaces wired
   (`serializer.py:488-490`, `:529-530`, `:538-547`, `:586-597`;
   `builder/runtime.py:1679-1704`) plus `HookAborted` carrying `reason`,
   `cost_usd`, `ceiling_usd` (`registry.py:2722-2739`) — D6 verbatim.
3. **Tools, gates, retries.** OpenRouter sees "tools were included"; the app sees
   which tool, what query, how many results, `tool_status`, `run_attempts`,
   `retry_count` (`serializer.py:470-490`, `:562-570`, `:768-802`) — so D2 and D4
   are unreachable from the other side.
4. **No per-call request mutation.** SUPPLEMENT needs a run-scoped `trace` object
   on every request. I counted **eight** `LLM(...)` sites
   (`brief_crew.py:96,113,121`; `validator_crew.py:155,194,352,407`;
   `builder/runtime.py:636,881`), only **three** of which pass
   `additional_params` today (`validator_crew.py:354`, `:409`, `runtime.py:887`).
   Five must change, `extra_body`'s `provider` key is already contended
   (`config.py:1196-1200`), and the next flow anyone writes is untraced-by-run —
   a generalisation hole in a programme whose C1/C2 exist to close exactly it.
5. **The shared bucket stops being this app's problem**, because the emitter picks
   the project: only **10 of 40** traces are this app, **27%** of its cost (§6.2).

**On the other two apps: contamination, not a feature.** That they are the same
owner's makes it forgivable, not useful. Every first-class aggregate — Home cost,
`metrics/daily`, Sessions, Users — is 73% somebody else's, and the only separator
is `openrouter.api_key_name`, a metadata key with no console `Group by` and no
API `where`. Under REPLACE this app writes to its own project and the question
dissolves — or, if Hobby forbids a second project (**NOT VERIFIED**; neither
inventory opened Billing), to an `environment` the broadcast does not set.

## 3. Two things REPLACE must fix in the app, not in Langfuse

**(a) The usage figures are incomplete today** (§0). `langfuse-inventory.md` §3
records **761 of the Scoper's 1,006 output tokens were reasoning** — visible only
because OpenRouter forwards `gen_ai.usage.output_tokens.reasoning`. Turn the
broadcast off without widening `_USAGE_ALIASES` and that goes dark.

**(b) CLI runs would become invisible.** `capture_events` is entered in exactly
one place, `registry.py:2694` (`app-surface.md` §1.2), so `validate --idea …` has
no capture scope; today those calls still reach Langfuse via the broadcast and
under REPLACE they reach nothing. A real regression, cheaply bounded: open a
`capture_events` scope in the CLI entrypoints, or at minimum log once that no
trace is written — silent absence is the one outcome to refuse.

## 4. Reconciliation under REPLACE (E1, E5)

The circularity worry is right in form. The answer is that the independent check
is **not** the Logs page — `openrouter-forwarding.md` §1 is explicit that
`/activity` "answers 'how much', never 'which request'" — but
`GET /api/v1/generation?id=<response_id>`, per call, on a field the app already
records. E5 becomes a three-way join — app frames (`response_id`, model, tokens,
estimate) × Langfuse (`usage_details`, `cost_details`) × OpenRouter
(`total_cost`, `native_tokens_*`, `provider_responses`) — and E1 two greppable
assertions: `count(GENERATION in session) == count(LLM "after" frames)`, and
`count(observations carrying "openrouter.source" or scope.name == "openrouter")
== 0`. "A genuine discrepancy is a bug" survives because the third party is still
in the loop: queried, rather than trusted to arrive. The residual — a systematic
exporter bug dropping, say, every third generation — is caught only by that
cross-check, so it must be a **committed script run on every proof run**.

## 5. Verdict

# REPLACE.

**The three strongest reasons.**

1. **Most criteria are about things OpenRouter structurally cannot see, and no
   configuration reaches them**: A1–A3 (run boundary), B1–B2 (agent, task),
   B3/D1/D2/D6 (failures producing no HTTP 200 and so no trace), B4 (orchestration
   time), B6 (scores), C1–C2 (names invented later), D3 (a cancel between calls).
   Keeping a layer that answers none of them, to preserve one number a 478 ms GET
   returns better, inverts the cost.
2. **The one number worth keeping is recoverable, and recovering it beats
   inheriting it** (§1): the generation record carries true `total_cost` *and*
   `provider_responses` *and* the reasoning/cached split — of which the broadcast
   forwards two and the app's own frames none.
3. **SUPPLEMENT's join rests on an undocumented derivation already misread once
   here, a day after it was measured.** `sha256(s)[:32]` is not a promise;
   `parent_span_id` was accepted pointing at nothing, silently; `span_name` does
   not do what its documentation says. Correctness that is invisible when it
   breaks is wrong for a bar of "a genuine discrepancy is a bug".

**The two strongest reasons against my own verdict.**

1. **One emitter means no free canary.** Two independent paths disagreeing is a
   standing zero-effort alarm on the app's own instrumentation — exactly what
   would have caught `cost_usd = 0.0` over 128,069 tokens the day it shipped.
   REPLACE trades that for a script somebody must keep running.
2. **Turning off a working feed to build its replacement is the riskier order.**
   The broadcast works and the one full run in the project is legible end to end
   (`langfuse-inventory.md` §6.3); REPLACE leaves the project with nothing until
   the exporter is proved, and makes CLI runs invisible permanently. Mitigation
   is sequencing, not design: exclude the key **last**.

**What the chosen design must build.**

1. `src/brief_crew/observability/` — exporter at `StreamSinkAdapter.on_frames`
   (`registry.py:966`): `put_nowait` onto a bounded queue, daemon consumer, in
   the shape of `_PersistenceWriter` (`:680-830`) — drop counters, bounded
   `flush()`, idempotent `close()`, total emit paths, and **no lock the capture
   path takes** (`:1298-1307`). **Drain ≤ 0.25 s**: no `start_time` exists, so a
   batched flush fails B4.
2. **Trace lifecycle in `RunRegistry._execute`** (`:2669-2774`): open inside
   `capture_events` (`:2694`); end at `HookAborted` (`:2711`), `Exception`
   (`:2740`) and completion (`:2769`); *suspend* at `HumanFeedbackPending`
   (`:2765`). `sessionId = run_id`, `userId = record.user_id or "anonymous"`,
   `environment` in {`synthetic`, `live`}.
3. **Span tree from frames**: run → node (`current_node_scope`) → agent/task →
   tool / generation, attached cross-thread via
   `start_observation(trace_context={"trace_id": …, "parent_span_id": …})`
   (`client.py:714-724`) — the answer to `app-surface.md` §10.3.
4. **Generation enrichment worker**: bounded queue of `response_id`s, one shared
   token bucket, the GET, then `update(cost_details=…, usage_details=…)` and
   `end(end_time=<frame ts, ns>)`; on failure keep the estimate and stamp
   `cost_source`. Emit `provider_responses[]` as child SPANs.
5. **Widen `normalize_usage`** with the `cached_prompt_tokens` /
   `reasoning_tokens` families, into the TOKEN frame and `usage_details`.
6. **Content policy per DoD §5.3**: SHA-256 prompt fingerprint, message count,
   char lengths; `LANGFUSE_CAPTURE_CONTENT=1` routes every string through
   `events.redaction.is_secret_key` — the existing list, never a second — plus
   key-prefix scrubbing. One walk, not two (`serializer.py:670-687`).
7. **Generic scores only** — guardrail pass/fail and `retry_count`
   (`serializer.py:562-570`), terminal outcome — and **a committed reconciliation
   script** (`scripts/observability/`) doing §4's join and the E1 assertion.
8. **Config**: `LANGFUSE_*` knobs in `config.py`, never a boot assertion
   (`app.py:675-677` guards money and secrets; telemetry must not refuse to
   boot). `uv add langfuse` under a new `observability` extra — 2 packages,
   `langfuse==4.15.1` + `wrapt`, no conflicts. Plus the CLI bound (§3b).

**The exact OpenRouter-side configuration change.** One field, on destination
`8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b` ("multi-agent-crew-ai"): **add the
`MultiAgentCrewAI` key to Excluded API Keys.** `api_key_hashes` is `null` today
(`part1-destinations-api.json`), documented as "all keys", and
`docs/broadcast-overview.md:210-212` states a destination may carry excluded keys
and that **"exclusions take precedence"**.

By exclusion, **not** by disabling the destination — disabling or deleting it
also stops forwarding for `WikiSkills` and `LTA_ML_PROBLEM`, the owner's other
work and outside this programme's mandate. Nothing else moves: Privacy Mode and
the three metadata categories stay off, because after exclusion this destination
no longer carries our traffic and its policy is not ours to set; sampling stays
at 1. The change lands **last**, after the exporter has passed E1 with the
duplicate still arriving and counted.

**Hardest DoD rows under this verdict.**

- **E5, by a distance** — where REPLACE's structural weakness lives. App and
  Langfuse agree by construction, so the check's whole independence rests on the
  `/generation` join, whose rate limit is unmeasured for that endpoint and which
  cannot see a call that never got a `response_id`.
- **B4** — no `start_time`, so every duration is when the exporter thread reached
  the frame. Achievable with a prompt drain and explicit `end_time`; the row most
  likely to fail quietly if the queue ever backs up. **E4** shares the hazard:
  `_on_frames` holds a non-reentrant lock, so the overhead measurement must run
  with the enrichment worker on or it measures half of it.
- **A3 and D3 across a gate pause** — a paused run must hold a trace open across
  a process boundary it may not survive, and a resume rebuilds the record with a
  new adapter and buffer (`registry.py:3209-3258`). Two segments joined by
  `sessionId` is the honest answer; D3's "no observation without an end time"
  finds out whether it was implemented.
- **C1 is easy here, hard under SUPPLEMENT**: frames carry no flow-specific names
  by construction, so the grep passes by design, not by discipline.
