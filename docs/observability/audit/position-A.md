# Position A — keep, supplement, or replace the OpenRouter→Langfuse layer

**Analyst A, 2026-09-05**, against `main` = `b65bd65`, CrewAI 1.15.18. I re-ran
what this argument leans on; **(verified here)** means I measured it myself.

## 0. Five things I checked first

**(a) The two inventories contradict each other on the central mechanism, and
the forwarding audit is right. (verified here)** `langfuse-inventory.md` §6.1
says *"the Langfuse trace id is still server-assigned ❌"* and *"two requests
sharing one `run_id` still produced two separate traces"*. Those are probes **d**
and **f**, which sent **different** `trace.trace_id` strings:

```text
sha256("obsprobe-trace-1788612874" )[:32] == 8b15b51c4f6c36711f217e68ad5c99ac
sha256("obsprobe-stream-1788612874")[:32] == dbd49206c2c8a478fcf97ce967645760
part3-langfuse-traces.json → 8b15b51c… holds 4 observations: 2 GENERATION + 2 SPAN
```

d1 and d2 **did** merge; `trace.trace_id` **does** set the trace id by
`sha256(s)[:32]`. The inventory's last §6.1 row is wrong; fix it before building.

**(b) `parent_span_id` is verbatim and a dangling parent is accepted. (verified
here)** The d1 generation carries `parentObservationId = "0123456789abcdef"` — an
observation that never existed — and Langfuse ingested and rendered it.
Observation ids are 16 hex chars. A parent *"never received"* leaves its child
*"shown at the trace root"*
([Troubleshooting & FAQ](https://langfuse.com/docs/observability/sdk/troubleshooting-and-faq)).
**No official statement says a *late* parent is re-joined**, and no join window
is documented; the circumstantial case is strong but it is inference.

**(c) A scoped `PRE_MODEL_CALL` hook *can* mutate `llm.additional_params`, and
the mutation *is* honoured on that call. (verified here)** SUPPLEMENT's
load-bearing mechanism, and it works: `agent_utils.py:580` `get_llm_response` →
`:504-505` `_prepare_llm_call` → `_setup_before_llm_call_hooks` (`:1943`), which
appends `get_scoped_hooks(PRE_MODEL_CALL)` (`:1970`); `hooks/llm_hooks.py:88` sets
`self.llm = executor.llm`, the **live object**, with `context.task`/`agent` beside
it. Only then `:582` `llm.call()` → `completion.py:1789-1800`, which
builds `params` **fresh per call** and does `params.update(self.additional_params)`
at `:1800` (the guardrail's `agent.kickoff` takes the same path).

**(d) `LLMCallFailedEvent` carries no `response_id`. (verified here)**
`crewai/events/types/llm_events.py:117-121` declares only `error` plus
`LLMEventBase`, while `LLMCallCompletedEvent` (`:99`) and `LLMStreamChunkEvent`
(`:143`) do carry it. This decides §1.1.

**(e) The Langfuse SDK will not let a client choose an observation id.** *"trace
IDs are 32-character lowercase hex strings, observation IDs are 16-character…
**You cannot set arbitrary observation IDs**, but you can generate deterministic
trace IDs"* ([Instrumentation](https://langfuse.com/docs/observability/sdk/instrumentation)).
A *parent* id may be supplied via `trace_context`; the id of the span you create
may not. And `/api/public/ingestion` — the one API where ids are free — is
**sunset 2026-11-16** on Cloud. §1.4 turns on this.

## 1. The design, and where it breaks

**SUPPLEMENT is buildable and I want to be clear that it is**: trace id
`sha256(run_id)[:32]` app-side matched by `trace.trace_id = run_id`;
`session_id`/`user` → `trace.sessionId`/`userId` verbatim (probe c/d); arbitrary
`agent_role`/`task_name`/`node_id` → observation metadata; B5's fingerprint as
`trace.prompt_sha256` from `context.messages`. Construction-time stamping is
**not** sufficient — a task span is per task and the guardrail agent reuses the
task agent's own `llm` (`task.py:435`) — so the §0(c) call-time hook is needed.
Nothing here is flow-specific: every injected string comes from CrewAI's own
event and hook objects, so C1/C2 do not discriminate.

### 1.1 The failure path cannot be de-duplicated in-app (E1, D4, B3)

OpenRouter forwards nothing for a request it refuses — probe **e** produced no
trace, no observation, no error record — and whether a request that *reaches a
provider* then fails is forwarded is **NOT VERIFIED**. So the app must emit failed
generations itself. But `LLMCallFailedEvent` has no `response_id` (§0(d)), the
only field that could say whether OpenRouter holds a record, so it cannot decide
per failure whether emitting creates a duplicate. E1 asks for "no second copy of
any call"; that is not a measurement the app can make. And the exporter must write
GENERATION observations **anyway**, for the failures D4 and B3 require: SUPPLEMENT
saves only the success branch, and buys a judgement the app cannot make.

### 1.2 The content policy becomes unfalsifiable in this repository (E3, B5)

Privacy Mode is **off**, so `trace.input` is the full messages array (system
prompts to 29,519 chars, the user's idea verbatim, tool results verbatim) and
`trace.output.rawRequest` is **the entire request body**. Decision 3 makes
content default-off and E3 demands a committed test proving the exported payload
carries no content and no credential shape *with a planted marker*. Under
SUPPLEMENT half that payload is built by a third party from a body this repo does
not fully control, so **no committed test here can assert anything about it** —
E3 becomes a live re-probe after every OpenRouter config change. Privacy Mode is
one checkbox, but the docs list exactly two things it strips ("Input messages",
"Output choices") and say nothing about `rawRequest`, where a planted key lands.
Same shape as app-surface §6.4's leak, except `events/redaction.py` cannot run.

### 1.3 SUPPLEMENT makes observability edit the product's wire traffic

Section E is titled *"Observability must not change what the app does"*, and
SUPPLEMENT's mechanism is a hot-path hook mutating the outgoing request.
**Key contention:** `config.py:1173-1240` assembles one `extra_body` and warns
three times in its comments — *"JSON has no merge, so one `provider` object is
written once here rather than by two callers of whom the second silently wins"* —
and the hook becomes that second writer, over the `provider.max_price` ceiling. **Shared mutable state:** safe only because LLMs are per-agent-per-run
and one agent's calls are sequential — a property of the two current flows, not
of the design. **Disclosure:** it puts `run_id`, the owner's `user_id`, agent
roles and task names into a third party's permanent logs. REPLACE reads
`on_frames`, off the critical path, and writes nothing.

### 1.4 The parent join is harder than it looks, and rests on an undocumented hash

**The app cannot mint the span id it must hand to OpenRouter (§0(e))** — it can
only *read* the id of a span it already created. But app spans are created
asynchronously on the exporter's queue thread from `on_frames`, while the hook
runs synchronously on the executor thread at call time, so SUPPLEMENT needs the
task span to exist *before* the task's first LLM call — an ordering dependency
between telemetry and the model's hot path that REPLACE does not have.
Every escape is bad — spans in the hook (telemetry on the critical path), spans
under `_capture_lock` (§7.2 forbids it), a custom `IdGenerator`, or the API that
is being sunset.

**The derivation is undocumented** — the forwarding audit's own words: *"an
implementation detail OpenRouter has not promised to keep."* Under SUPPLEMENT the
app's trace id **must** be `sha256(run_id)[:32]`; if that changes, app spans and
generations silently split into two traces with no error anywhere.
Under REPLACE nothing depends on it: `run_id` is `str(uuid.uuid4())`
(`registry.py:1579`), so `UUID(run_id).hex` **is already a valid 32-hex trace
id** — the run id minus the dashes, exactly what decision 1's "without a lookup
table" asks for. Add that three of the seven documented `trace` fields do not
work as documented: `span_name`, `release` and `tags`.

## 2. What SUPPLEMENT genuinely buys

**True billed cost** — `total_cost` matched `GET /api/v1/generation` 6/6 to the
last digit, rides on the observation as `costDetails`, and *"ingested values take
priority over inferred ones"*
([Token & Cost Tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking));
`compute_cost_usd` is an estimate by its own docstring (`config.py:486-505`) and
`:nitro` runs it up to 1.8x low (`NITRO_PRICE_FACTOR`, `config.py:2399`). And
**provider attribution plus the SDK's invisible retries** — `provider attempt N`
spans, endpoint id, permaslug, latency stages, and the two httpx retries
`max_retries` (`completion.py:223`) makes silently. Both are real. **Neither survives the reconciliation rows.** Under SUPPLEMENT the
true cost sits in Langfuse while the app's UI, `run_node_metrics` and the
`MAX_RUN_COST_USD` ceiling keep the estimate — two permanently disagreeing
figures with no reconciliation path, and E5 says "close enough is not a status".
The app already holds the key: `response_id` is on every LLM `after` frame
(`serializer.py:529`) and `config.py:1086-1089` names the use. Ten free
`GET /api/v1/generation` calls per run give the billed figure **attributed to
node, agent and task**, closing item 41 — SUPPLEMENT does not.

## VERDICT: **REPLACE**

**Three strongest reasons.**
1. **SUPPLEMENT does not reduce the build, and adds a decision the app cannot
   make.** Every row but the cost half of E5 is app-side (A1–A3, B1–B4, B6,
   C1–C3, D1–D6, E1–E4) and the exporter must write GENERATION observations
   regardless; keeping the copy saves one branch and buys an undecidable
   de-duplication instead (§1.1).
2. **E3 becomes unfalsifiable in-repo, and it is the row this project is most
   likely to be wrong about.** A committed test can prove absence from a payload
   this repo builds; nothing here can prove absence from `rawRequest` — echoed
   verbatim, undocumented under Privacy Mode, where a planted key lands (§1.2).
3. **REPLACE gets a truer cost and a simpler identity**: the billed figure joined
   to node/agent/task, and a trace id of `UUID(run_id).hex` rather than an
   undocumented hash that can silently split every trace in two (§1.4).

**Two strongest reasons against my own verdict.**
1. **I am trading a *measured* number for a *pipeline*.** OpenRouter's cost is
   exact 6/6 today, free and already working; my replacement has never been run,
   needs `get-generation` queryable promptly after a run, and adds a network
   dependency to E5; if the backfill slips it ships a *worse* figure than today's.
2. **REPLACE permanently loses the SDK's transport retries.** A 429 retried twice
   inside httpx raises no event and no frame, while OpenRouter would very likely
   see the attempts, so that spend and latency go invisible — a real hole in B4.
   I accept it only because whether they are forwarded is unverified too.

## What the chosen design must build

`src/brief_crew/observability/` (B-EXP) and `scripts/observability/` (B-CFG):

1. **Queue-and-daemon exporter** copying `_PersistenceWriter`
   (`registry.py:680-830`) in shape — `put_nowait` only, bounded queue, daemon
   thread, drop counters, bounded `flush()`/`close()`, total `try/except`.
   Attach at `StreamSinkAdapter.on_frames` (`registry.py:966`), which runs under
   `_capture_lock` (`adapter.py:51`): emit no frame, never block, take no lock the
   capture path takes. Ship over **OTLP**, not `/api/public/ingestion`.
2. **Trace lifecycle at `RunRegistry._execute`** (`:2669-2774`): open inside
   `capture_events` (`:2694`); close on `HookAborted` (`:2711`, carrying
   `stop_reason`/`cost_usd`/`ceiling_usd` for D6), `Exception` (`:2740`) and
   completion (`:2769`); *suspend* on `HumanFeedbackPending` (`:2765`), which is
   what keeps A1 whole across a gate and a restart. `trace_id = UUID(run_id).hex`,
   `sessionId = run_id`, `userId = owner or "anonymous"`, `environment` = the mode.
3. **Frame→observation mapper** on `FrameKind`/`stage`/`node_id` only — no role,
   task, tool, crew or flow string in the module (C1); parents from a per-run
   span-handle map under the adapter's lock (app-surface §10.3 tier 3), since ids
   cannot be pre-minted (§0(e)); unknown event → generic EVENT (C3).
4. **GENERATION observations** from the LLM `after` + `TOKEN` frame pair:
   `model`, `usageDetails`, `costDetails` (`compute_cost_usd`; `None`, never
   `0.0`), `response_id` in metadata, `level=ERROR`/`statusMessage` on failures.
5. **Run-scoped `PRE_MODEL_CALL` hook** beside the cancel guard, for the **B5
   fingerprint only** — SHA-256 of `context.messages`, message count, char
   lengths. It reads; it never writes `additional_params`.
6. **Generic scores** (B6) — guardrail pass/fail, `retry_count`
   (`serializer.py:562-570`), terminal outcome — plus redaction reuse:
   `events.redaction.is_secret_key`, one walk, key-prefix scrubbing,
   `LANGFUSE_CAPTURE_CONTENT` off by default.
7. **`scripts/observability/reconcile.py`**: NDJSON → `response_id` →
   `GET /api/v1/generation` → billed cost per call, into `RECONCILIATION.md` (E1,
   E5) **and** a Langfuse **score** per generation — the one surface documented as
   order-independent and writable by a second producer. Never update a closed one.
8. **`uv add langfuse`** (4.15.1 + `wrapt`) under an `observability` extra, not
   base deps; `uv.lock` in the same commit. Client flushed beside
   `registry.close()` in `lifespan` (`app.py:762-770`); never a startup
   assertion (`app.py:675-677`).

## The exact OpenRouter-side change required

**One field, on destination `8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b`
("multi-agent-crew-ai", UI route `15910`): add this application's
`MultiAgentCrewAI` key to *Excluded API Keys*, moving `api_key_hashes` from
`null` to a one-entry exclusion.** Nothing else moves — Broadcast stays ON,
Privacy Mode as it is, regions, sampling and filter rules untouched.

`api_key_hashes: null` makes the destination **workspace-wide across 13 keys**,
and two thirds of the project is not this app (`LTA_ML_PROBLEM` 14, `WikiSkills`
16, `MultiAgentCrewAI` 15 over 24h), so disabling or deleting it would take
observability from two unrelated applications; excluding one key stops the
duplicate generations E1 forbids and leaves the other twelve untouched. One click
to reverse, and the smallest diff against the baseline F1 exists to protect.
Record as a finding, not a change: this app shares one Langfuse project with two
others, so any project-level cost is not this product's; a second project for the
other keys is the real fix, out of scope here.

## The DoD rows that are hardest under REPLACE

- **E5, hardest by a distance.** Giving up the free exact cost puts the row on
  the `response_id` → `get-generation` backfill, with three shortfalls each
  needing a *named cause*: a record not queryable when the script runs; embeddings,
  rerank and Firecrawl, which raise no LLM event and sit in nobody's total
  (`registry.py:1319-1326`); and the transport retries nothing can count.
- **E1.** Its literal test is "Langfuse generations == app LLM frames", and the
  key exclusion is what makes it true (recorded with its reason, F1); until
  applied it fails by *double-counting*, the mode that looks like success.
- **D3, cancelled with zero open spans.** `HookAborted` emits **no CrewAI
  event**, so spans opened before the abort get no closing frame; the exporter
  must close every open span from the terminal `RUN_STATE` frame — the same code
  that stops an *interrupted* process leaving a dangling trace (app-surface §5.6).
- **B3/D1/D2.** The app records `str(exc)` and a class name and **never a
  traceback** (`builder/runtime.py:1622-1633`), so "exception class and a redacted
  message" is the ceiling without new capture.
- **B6, for a reason outside the code.** Hobby retention is **30 days** and the
  plan includes **50k units/month** (traces + observations + scores); a validator
  run is ~40–60 units here against ~20 today, so drift is chartable only within
  30 days and a few hundred runs a month.
