# 08 · Observability — CrewAI AMP

**Decision: this project uses CrewAI AMP for tracing**, backed by a Postgres
`run_metrics` table as the durable record. LiteLLM and LangSmith were evaluated
and rejected — reasoning in §6.

**Verified 2026-08-29** against the live `app.crewai.com` account, the installed
`crewai==1.15.18` source, and real API calls. Where docs and code disagree, this
follows the code and says so.

> 🔨 **Implementation status (2026-08-29).** Partly built, and the gap is
> specific enough to be worth naming.
>
> **Built:** `persist` in `src/brief_crew/main.py` writes a run record to
> `output/last_run.json` carrying `run_id`, `topic`, `route`,
> `successful_requests`, the three token counts and a dollar figure — the same
> shape `runs` + `run_metrics` want, so moving it to Postgres is a change of
> destination rather than of structure. Cost is **computed** from tokens against
> the §3 price table, as this file requires, because OpenRouter's own cost figure
> never reaches the event.
>
> **Not built:** the `BaseEventListener`. Without it there is no per-agent split,
> because `CrewOutput.token_usage` aggregates the whole crew and does not carry
> `model`. The recorded figure is therefore priced entirely at the **escalation
> tier** and is an **upper bound**, not the bill — it is labelled
> `cost_usd_upper_bound` in the JSON so nobody mistakes it for measured spend.
>
> This matters more than it looks: the crew deliberately mixes a $0.075 tier and
> a $0.75 tier, so an undifferentiated total is exactly the number that cannot
> answer any of the four A/B comparisons. Subscribing to
> `LLMCallCompletedEvent` — which carries `model`, `task_id` and `agent_id` — is
> what turns the cost claim into a measurement. It is the highest-value piece of
> this file still outstanding.
>
> **Also not set:** `CREWAI_TRACING_ENABLED` is absent from `.env`, so AMP
> tracing is off. Add it there rather than passing `tracing=True`, for the
> first-run consent reason in §3.
>
> Confirmed at the end of the first `crewai run`: *"Info: Tracing is disabled."*

### What the run record actually contains (measured)

`output/last_run.json`, written by the Flow's `persist` step after a real
`crewai run` on 2026-08-29:

```json
{ "run_id": "3c0ebab7-…", "topic": "cashless payments in Singapore",
  "route": "cache_miss", "successful_requests": 13,
  "prompt_tokens": 109104, "completion_tokens": 30085,
  "total_tokens": 139189, "cost_usd_upper_bound": 0.19464675 }
```

Two runs are now on record, and the comparison is itself a finding:

| | Track A (`run_crew`) | Track B (`crewai run`) |
|---|---|---|
| LLM calls | **9** | **13** |
| Prompt / completion tokens | 178,711 / 13,614 | 109,104 / 30,085 |
| Cost (escalation-tier upper bound) | ≤ $0.1851 | ≤ $0.1946 |

Same topic, comparable brief, **+4 calls** on the Flow — the retrieval round-trip
plus the Flow's own crew construction. That is the Track B overhead, paid on
every miss and only repaid on a later hit. It is exactly the kind of number
slide 53 asks for, and it exists because the run record is written, not because
anyone remembered it.

### ⚠️ A cost figure that silently reads zero

Worth recording as a class of bug, not just an incident. `persist` printed

```python
record.get('cost_usd', 0)          # key never existed
```

against a dict whose key is `cost_usd_upper_bound`. `dict.get()` with a default
cannot fail, so every run logged a confident **`cost=$0.000000`** while
`last_run.json` carried the correct figure all along. Nothing raised, and the
number was plausible enough to read past — an unmeasured system and a system
measuring the wrong key look identical from the console.

Fixed, and the printed line now says `cost<=$0.194647 (upper bound,
escalation-tier priced)` — naming the bound in the output rather than leaving a
bare number to be mistaken for the bill. **Prefer `record["key"]` over
`.get("key", default)` for values you intend to display**: a `KeyError` at the
moment of the typo is far cheaper than a plausible zero.

---

## 1. What AMP gives you

CrewAI's first-party platform — renamed from "CrewAI Enterprise" in Oct 2025, so
URLs and CLI subcommands still say `enterprise`.

Confirmed on the live account:

```
Current Plan:      Free
Usage This Month:  0 / 50 included executions
Plans:             Free · Enterprise (Custom)
```

There is **no mid-tier**. A $25/mo Professional plan existed at launch and was
removed. Do not plan around a paid tier that is not published.

| Section | Contents |
|---|---|
| Build | Automations · Crew Studio · Agents Repository · Tools & Integrations · Skills Repository |
| Operate | **Traces** · LLM Connections · Environment Variables |
| Manage | Usage · Billing · Settings |
| Settings | Organization · Members · Roles · Billing · Integrations · Git Repositories · Secret Providers · Workload Identity · Account |

Traces dashboard: `app.crewai.com/crewai_plus/trace_batches`.

Status page `status.crewai.com` is real (90-day uptime 99.98–100%), but **no SLA
is published**.

---

## 2. Enabling it — do it by environment variable

```dotenv
CREWAI_TRACING_ENABLED=true
```

This is the right switch for three separate reasons, not just convenience.

### Precedence, from `tracing/utils.py:108`

```python
if override is True:  return True     # Crew(tracing=True) / Flow(tracing=True)
if override is False: return False
env = os.getenv("CREWAI_TRACING_ENABLED", "").lower()
if env in ("true", "1"): return True
return data.get("trace_consent", False) is not False
```

> ⚠️ **`CREWAI_TRACING_ENABLED=false` does NOT disable tracing.** There is no
> branch returning `False` for it — it simply fails the `("true","1")` test and
> falls through to stored consent, which may still be `true`. Only
> `tracing=False` in code disables absolutely.

### It defuses the headless consent trap

On a first run with no TTY, the consent prompt returns `False`
(`tracing/utils.py:498` — *"Skip prompt in non-interactive contexts (CI, API
servers, Docker…)"*) and then **permanently writes `trace_consent: false`**.
Every later run is silently untraced.

Setting the env var bypasses the first-run flow entirely, so this never happens.
Good news: it means no hang in a container — but you must set the variable or you
get silence.

### Flows are supported natively

`Flow` has its own field — `crewai/flow/runtime/__init__.py:578`,
`tracing: bool | None`, resolved at line 838 through the same
`should_enable_tracing`. Track B's Flow architecture works unchanged.

> ⚠️ **Nested Crews do not inherit a Flow's tracing.** Both resolve
> independently at construction, writing to a contextvar with no restore. A
> `Crew(...)` built inside a Flow step with `tracing` left at `None` can
> **overwrite the contextvar to `False`** for the rest of that context. Set
> `tracing=True` explicitly on every Crew constructed inside a Flow step, or
> rely on the env var, which covers both.

---

## 3. Deploying it — the Render constraint

**Authenticated tracing from a Render container is not achievable as designed.**
This is the single most important operational fact in this file.

| Finding | Evidence |
|---|---|
| No env var supplies a tracing credential | `get_auth_token()` → `TokenManager().get_token()` reads **only** an encrypted file. `CREWAI_USER_PAT` exists but is used solely by `crewai/skills/registry.py:251` |
| Token lives on disk | `~/.local/share/crewai/credentials/tokens.enc` + `secret.key`, mode `0700` |
| Token **expires**, no refresh | `get_token()` checks expiry; zero `refresh_token` support anywhere |
| Written only by an interactive flow | `crewai login` is an OAuth2 device-code flow needing a browser |

`CREWAI_USER_ID` and `CREWAI_ORG_ID` look like credentials and are not — they are
cosmetic payload labels defaulting to `"anonymous"` and `""`
(`trace_listener.py:197-198`).

### What happens instead: ephemeral tracing

On `AuthError` or a 401/403, the batch manager falls back to **ephemeral** mode
(`trace_batch_manager.py:204`). Tracing still works and still uploads — you get a
short-lived shareable trace URL — but it is **not attributed to your org and does
not appear in your dashboard**.

### Therefore

| Environment | Approach |
|---|---|
| **Local / dev** | `crewai login` once, then `CREWAI_TRACING_ENABLED=true`. Full authenticated traces in your dashboard. This is where AMP earns its place. |
| **Render** | Postgres `run_metrics` is the durable record. Optionally leave tracing on for ephemeral traces; do **not** bake `tokens.enc` into an image — it is a credential in a build artifact and it expires with no renewal path. |

That is not a downgrade. The two answer different questions: AMP shows you *what
the agents did*, `run_metrics` shows you *what every run cost*.

### Failure isolation — tracing cannot break a run

Two independent boundaries: the tracing code wraps every network call in
`try/except` returning gracefully (*"Continuing without tracing"*,
`trace_batch_manager.py:195`), and the event bus itself never propagates handler
exceptions (`events/utils/handlers.py:57`). An unreachable endpoint, expired
token or DNS failure costs you a console warning, not the run.

### Flush timing

Events buffer in memory and upload as **one batch** at crew/flow completion, on a
background thread — so it does not delay `kickoff()`'s return. Completion is only
guaranteed by a 30-second `atexit` flush.

> ⚠️ A container that hard-kills the process immediately after the entrypoint
> returns can drop the trace mid-flight. Call `crewai_event_bus.flush()`
> explicitly before exiting a one-shot job.

---

## 4. Before you trust it — two things to verify, and one to accept

### Unresolved: does a local traced run burn one of your 50 executions?

The docs do not say. Evidence points both ways:

- **Toward "no"** — on the pricing page the execution rows sit nested under
  **Automations** (Free = 2 deployed automations). **Tracing** is a separate row
  in a different category with a plain "Yes" and no numeric cap.
- **Toward "yes"** — the dashboard calls every traced run an "execution",
  including local ones.

**Test it empirically before relying on it:** run one traced crew, then check
whether `Settings → Billing` still reads `0 / 50`. That is a two-minute check and
it is the only reliable answer available.

### Unresolved: trace retention

**Not documented at any tier.** The 30/180-day figures in the privacy policy
apply to Google OAuth data, not traces. Do not assume traces persist.

### Accept, or do not enable: the payload is unredacted and may train models

Full LLM **prompts**, full **completions**, full **tool arguments** and full
**tool outputs** are serialised verbatim
(`trace_listener.py:944`, `safe_serialize_to_dict`). A `truncate_messages()`
helper exists in the tracing utils and is **never called** — dead code. Nothing
truncates or redacts.

For this project that means the topic string, scraped web content, and every
retrieved chunk leave the machine.

CrewAI's Terms of Use state that Customer Data may be used to *"improve and
develop products and services, including by training and developing models
and/or algorithms."* No opt-out was found in the public terms. **PII redaction is
Enterprise-only.** RBAC is Enterprise-only too.

This is fine for a public-topic research brief. It would not be fine for
confidential source material — and that judgement should be made deliberately,
per topic, not once.

---

## 5. Cost — AMP does not give it, and neither does the event bus

> **Correction.** An earlier draft of this file said to read OpenRouter's `cost`
> off the event stream. **That does not work**, and the reason is worth knowing.

`OpenAICompletion._extract_openai_token_usage` (`completion.py:2720`) builds an
explicit whitelist:

```python
result = {"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ...}
# + cached_prompt_tokens, reasoning_tokens
```

Arbitrary fields are never passed through, and CrewAI **never sets**
`extra_body={"usage": {"include": True}}`, so OpenRouter is not even asked for
cost. Verified with a real traced call:

```
event.usage: {'prompt_tokens': 19, 'completion_tokens': 90,
              'total_tokens': 109, 'cached_prompt_tokens': 0,
              'reasoning_tokens': 87}
has 'cost' key?  False
```

### So compute it

Multiply `event.usage` token counts by the §3 price table in
`00-shared-config.md`, keyed on `event.model`. Deterministic, no extra calls, no
dependency on a field CrewAI discards.

A direct OpenRouter call **with** `"usage": {"include": true}` does return the
billed figure (verified: `cost: 1.5175e-05`), so a reconciliation job against
OpenRouter's Activity API remains available if you ever need billed-exact
numbers.

### ⚠️ Reasoning tokens dominate the bill on `glm-5.3-flash`

Measured — same one-word prompt, three variants:

| Variant | Completion tokens | Reasoning | Cost |
|---|---|---|---|
| default | 71 | 68 | $1.92e-05 |
| **`reasoning_effort: "minimal"`** | **3** | **0** | **$2.18e-06** |
| `reasoning.exclude: true` | 21 | 18 | $1.34e-05 |

**The default burns ~95% of its completion tokens on reasoning**, billed at the
completion rate. Setting `reasoning_effort: "minimal"` is an **8.8× cost
reduction** on short mechanical calls.

Note `reasoning.exclude: true` only *hides* reasoning from the response — it is
still generated and still billed. It is not a cost control.

Apply `reasoning_effort: "minimal"` to the **Evaluator** (a rubric check needs no
deliberation) and test it on the Researcher. Leave the Analyst alone — that agent
exists precisely to reason.

---

## 6. Why not LiteLLM, why not LangSmith

### LiteLLM — no

OpenRouter resolves to a native provider, so LiteLLM is never imported. The
decisive detail, from `crewai/llm.py:2530`:

> *"Note: This only affects the litellm fallback path. Native providers don't use
> litellm callbacks — they emit events via base_llm.py."*

`LITELLM_SUCCESS_CALLBACKS="langfuse,langsmith"` is *the* LiteLLM route to
third-party observability, and **it never fires here**. Reaching LangSmith that
way would mean abandoning the native provider to force every call back through
LiteLLM.

That function also has a bug: the success-callback assignment sits inside the
`if failure_callbacks_str:` branch, so setting only the success variable assigns
nothing.

The standalone **LiteLLM Proxy** is a different product — virtual keys, budgets,
spend tracking, fallbacks. OpenRouter already does all of that. It would add a
second always-on service plus its own Postgres. Revisit only for cross-request
caching or multi-team RBAC.

### LangSmith — no

Absent from CrewAI's observability docs (which list Arize Phoenix, Braintrust,
Datadog, Galileo, LangDB, Langfuse, Langtrace, Maxim, MLflow, Neatlogs, OpenLIT,
Opik, Patronus, Portkey, TrueFoundry, Weave). LangSmith documents CrewAI only via
a Traceloop OpenTelemetry bridge, with an open bug — `langsmith-sdk#1350`,
"traces not showing for LLM calls when using CrewAI". No cost capture. Free tier
is 5,000 traces with 14-day retention, then $39/seat/month.

It is built for LangChain/LangGraph shops. This is not one.

**If AMP disappoints, the fallback is Langfuse** — CrewAI hosts its own guide, it
self-hosts, and its free tier is generous. Not LangSmith.

---

## 7. The durable record — Postgres `run_metrics`

AMP is the trace UI. Postgres is the system of record, because it survives
deploys, needs no auth story, and answers the cost question AMP cannot.

### Listener

> ⚠️ **Correction — never register a plain `def` handler if ordering matters.**
> The snippet below used to be written with `def _(source, event)`. Sync handlers
> run on a background `ThreadPoolExecutor`, and the pool **reorders them**:
> measured, **11 adjacent inversions in 200 paired events on the 10-worker
> pool**. For a metrics row that is harmless. For anything that assigns a
> sequence number at capture time, or that a UI replays in order, it corrupts the
> sequence itself — you get `NODE_END` before `NODE_START`.
>
> Two orderings measured at **0 inversions**: an `async def` handler, and the
> ContextVar-scoped **stream sink** (below). Use one of them. This is the one
> place where the code this spec used to recommend is actively wrong for a UI.

```python
from crewai.events import BaseEventListener
from crewai.events.event_bus import CrewAIEventsBus, crewai_event_bus
from crewai.events.types.llm_events import LLMCallCompletedEvent

class RunMetricsListener(BaseEventListener):
    def __init__(self) -> None:
        self.rows = {}          # set state BEFORE super().__init__()
        super().__init__()      # __init__ calls setup_listeners()

    def setup_listeners(self, bus: CrewAIEventsBus) -> None:
        @bus.on(LLMCallCompletedEvent)
        async def _(source, event):            # async def, NOT def — see above
            run_id = run_id_var.get()          # see concurrency note
            ...                                 # accumulate by run_id + agent_id
```

Construction *is* registration — `BaseEventListener.__init__` calls
`setup_listeners`, so instance state the handlers close over must exist first.

### Base fields on every event

`BaseEvent` (`events/base_events.py`) carries `timestamp`, `type`,
`source_fingerprint`, `source_type`, `fingerprint_metadata`, `task_id`,
`task_name`, `agent_id`, `agent_role`.

⚠️ **There is no field named `fingerprint`.** It is `source_fingerprint` (a UUID
string) and `fingerprint_metadata` (a dict). Guessing the short name yields
`None` silently, because these are Pydantic models with defaults rather than
strict attribute access.

### Useful events

| Event | Carries |
|---|---|
| `LLMCallCompletedEvent` | `usage`, `model`, `response_id`, `finish_reason`, `call_id` |
| `LLMStreamChunkEvent` | `chunk: str`, `call_id`, `response_id`, `tool_call` |
| `ToolUsageFinishedEvent` | `tool_name`, `tool_args`, `output`, **`from_cache`**, `started_at`/`finished_at` |
| `MethodExecutionFinishedEvent` | `method_name`, **`result`** |
| `CrewKickoffCompletedEvent` | `output`, `total_tokens` |
| `HumanFeedbackRequestedEvent` | `request_id`, `message`, `output`, `emit` — the gate opening |
| `HumanFeedbackReceivedEvent` | `request_id`, `method_name`, `feedback`, `outcome` — the gate closing |

⚠️ **Four events understates the surface, and the omissions matter for a UI.**
Three additions worth knowing:

- **`LLMStreamChunkEvent` is dispatched inline, in the thread emitting it** —
  not on the handler pool. A slow handler on this event directly slows token
  generation. Do no I/O in it.
- **`Flow.astream()` (`flow/runtime/__init__.py:2029`) is a supported
  alternative** to the bus entirely: it yields scoped public `StreamFrame`
  objects (`crewai/types/streaming.py:31`) already ordered per run.
- **Correlation is not uniform across event families.** Several families leave
  `agent_id` and/or `task_id` as `None` — flow-method and LLM events in
  particular, since an `LLM.call()` need not be inside a task. Any node
  attribution built on `agent_id` alone will quarantine a large fraction of
  frames. Resolve through a declared chain instead: task name → agent-role prefix
  → current Flow method (`crewai.flow.flow_context.current_flow_method_name`) →
  an explicit, *visible* unattributed node. See
  `src/brief_crew/events/registry.py`.

### Recording the router branch

There is no router-decision event, but a `@router` method's return value *is*
`MethodExecutionFinishedEvent.result`:

```python
@bus.on(MethodExecutionFinishedEvent)
def _(source, event):
    if event.method_name == "check_cache":
        route = event.result        # "cache_hit" | "cache_miss"
```

That populates `runs.route` (`07-deployment.md`) with no extra instrumentation.

### Flow-wide totals come free

`Flow.usage_metrics` (`flow/runtime/__init__.py:938`) already aggregates
`LLMCallCompletedEvent` usage across **every** kickoff in a flow run — Agent,
Crew or raw `LLM.call()` — correlated by a `current_flow_id` contextvar, flushed
before it returns. Use it for run totals; use your own listener only for the
per-agent and per-route breakdown.

Caveat from its own docstring: sibling kickoffs run **in parallel** under one
parent share a correlation id and can over-count.

> ⚠️ **That caveat is no longer hypothetical.** Validator Studio fans out to
> three sibling `@listen` research branches inside one run
> (`src/brief_crew/validator_flow.py`), which is exactly the shape the docstring
> warns about. Consequences:
>
> - `Flow.usage_metrics` stays usable as a **run total**, but treat it as a
>   cross-check, not as the source of truth.
> - **Per-node cost must be accumulated from `LLMCallCompletedEvent`, keyed on
>   `(run_id, node_id, model)`** — the branch identity has to come from node
>   attribution, because the correlation id cannot distinguish siblings. This is
>   what `src/brief_crew/service/registry.py` does.
> - When the two disagree, **log the discrepancy**; do not silently pick one.

### ⚠️ The event bus is a process-wide singleton

`crewai_event_bus` is a true singleton. A listener registered at import receives
events from **every** run in the process, including concurrent ones. Accumulating
into a dict keyed only by `agent_id` **will merge concurrent runs**.

Scope by contextvar, set before each kickoff:

```python
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)

token = run_id_var.set(run_id)
try:
    flow.kickoff(...)
finally:
    run_id_var.reset(token)
```

This is sound because the bus snapshots `contextvars.copy_context()` at emit
time. It is also exactly the technique CrewAI uses internally. Smoke-test two
concurrent runs before trusting it.

**Better than mitigating the singleton: remove it from the path.** ContextVar
scoping is a correct *mitigation* — a process-wide listener still sees every run
and is trusted to filter. A **stream sink** removes the problem structurally: the
sink object itself lives in a ContextVar
(`crewai.events.stream_context.add_stream_sink`), so a run's sink is only ever
reachable from that run's context and cross-run leakage is not possible rather
than merely avoided. It also captures **inline and in order** — see the ordering
correction at the top of this section.

```python
from crewai.events.stream_context import add_stream_sink, reset_stream_sinks

token = add_stream_sink(adapter)      # adapter(source, event) -> None
try:
    flow.kickoff(...)
finally:
    reset_stream_sinks(token)
```

Prefer this for anything a UI orders or sequences; keep the process-wide listener
for coarse metrics where a lost or reordered row is tolerable. See
`src/brief_crew/events/context.py`.

### Handler behaviour

Sync handlers run on a background `ThreadPoolExecutor`, so they add no latency to
the call being observed — **but see the ordering correction above: that same pool
is what reorders them.** **Handler exceptions are caught and logged, never
propagated** — a failing Postgres write degrades observability silently rather
than breaking the run. Which also means you must monitor the writer itself.

The swallowing has a Windows-specific trap. CrewAI's Rich console formatter
prints emoji; on a `cp1252` console every handler raises `UnicodeEncodeError`,
and because the exception is swallowed the run continues while the entire trace
disappears. **Set `PYTHONIOENCODING=utf-8` in the service environment** (or
reconfigure `sys.stdout`/`sys.stderr` at import, as `src/brief_crew/__init__.py`
does).

`Crew.kickoff()` does **not** flush after emitting `CrewKickoffCompletedEvent`,
so a handler writing the final row may still be in flight when it returns. Call
`crewai_event_bus.flush()` after `kickoff()` if the response depends on that row.
`Flow` already awaits its `FlowFinishedEvent` handlers.

---

## 8. Setup

```bash
crewai login                       # interactive, local only
crewai traces enable
```

Then in `.env` / Render:

```dotenv
CREWAI_TRACING_ENABLED=true
```

> ⚠️ **Windows:** `crewai traces status` crashes with
> `UnicodeEncodeError: 'charmap' codec can't encode character '⚪'` — it prints a
> status glyph to a cp1252 console. It reads like an auth failure and is not.
> Use `PYTHONIOENCODING=utf-8 crewai traces status`.

### Checklist

1. `crewai login` locally, set `CREWAI_TRACING_ENABLED=true`, run one crew.
2. Confirm the trace appears at `app.crewai.com/crewai_plus/trace_batches`.
3. **Check whether `Settings → Billing` still reads `0 / 50`** — this answers the
   quota question for your account definitively.
4. Ship the `RunMetricsListener` writing to Postgres. That is the durable record
   regardless of what AMP does.
5. On Render, expect ephemeral traces. Do not ship `tokens.enc`.
