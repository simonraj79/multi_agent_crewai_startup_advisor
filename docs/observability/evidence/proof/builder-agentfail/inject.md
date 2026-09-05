# `builder-agentfail` - how the agent is made to fail, on the PAID backend

Written 2026-09-05 by V-PROOF-DOCS, before any paid run. Every file:line below
was read at the working tree of that date; every measured line says *measured*
and carries the command that produced it.

`document.json` beside this file is the exact `document` body to POST.
`synthetic-check.txt` beside it is the proof that the document validates,
publishes and launches - **on a synthetic backend, which does not exercise the
failure**.

> **Line numbers, and one hazard.** Everything below was read at the working
> tree of 2026-09-05, while another agent was actively editing
> `service/app.py`, `service/registry.py`, `events/serializer.py` and
> `src/brief_crew/observability/`.
> `app.py` moved by about 28 lines and `serializer.py` by about 80 *during*
> this pass, so every citation into
> those two files was re-derived from a grep anchor at the end of it. If a
> number here does not land, grep the quoted symbol rather than reading around
> it: the anchor is the contract, the line is not.

---

## 1. The plan's own injection is REFUSED before the run can start

PLAN.md, "Failure injection, engine-neutral":

> **Failing agent**: on `builder-agentfail`, set the authored agent's model to
> `openrouter/nonexistent/model-that-is-not-served` (or whichever string the
> document schema accepts; it must keep the `openrouter/` prefix).

The document **schema** does accept it - `ModelSlug`
(`builder/document.py:110-115`) is length-bounded text and its own comment says
it checks "SHAPE only". But the **validator** does not, and neither does
publish. `builder/registry.py:177-251` reports `model-unknown` at severity
`error` for any id the roster has no row for, and `builder/__init__.py:157-161`
folds `model_problems` into `validate_document`, which
`builder/compiler.py:1755` folds into `document_problems`, which
`compile_document` runs before it compiles anything - so publish answers **422**
(`service/builder_api.py:1746-1755`).

**Measured** against the live validate route on the synthetic backend,
2026-09-05, using this document with only `llm.model` changed:

```text
POST /api/builder/validate -> HTTP 200
valid = False
 - error model-unknown         | sound_the_channel | llm.model |
     'nonexistent/model-that-is-not-served' is not a model this build offers, so
     llm.model names something no run could resolve. Pick one from the model picker;
     the roster is at GET /api/builder/models
 - error budget-unpriced-model | (graph)           |
     this graph cannot be priced: openrouter/nonexistent/model-that-is-not-served has
     no entry in PRICES, so every call it makes would contribute $0.00 to a total that
     is supposed to bound spend. Add the model to data/models.json in the same commit
     that names it
```

Two independent refusals, either of which is fatal. `app-surface.md`
section 9.2(B) already half-anticipated this - *"Publishing such a node is
refused at the registry door, so the realistic version is a model id the
catalogue no longer serves"* - but the roster is regenerated **from** the live
catalogue (`config.py:171-190`, `MODEL_REGISTRY_PATH`), so "in the roster and
no longer served" is a state this build does not have on the day of the run.

**PLAN.md's line "or whichever string the document schema accepts" is therefore
the operative clause, and this file exercises it.**

## 2. The injection used: a request the provider refuses, on a real model

The model stays a real roster model - `google/gemini-3.5-flash-lite`, the cheap
tier - and the **request** is made unserveable instead:

```json
"llm": { "model": "google/gemini-3.5-flash-lite", "temperature": 0.2, "max_tokens": 2000000000 }
```

This is the same failure class as section 9.2(B) - a *provider* failure, an LLM
call refused, zero tokens - reached through a field the schema deliberately
leaves unbounded rather than through a model id it checks.

### Why the schema accepts it, in the schema's own words

`builder/document.py:256-260`, `LlmConfig.max_tokens`:

```python
    # No ceiling. What a completion COSTS is bounded by MAX_RUN_COST_USD, which
    # is the layer that can measure money; inventing a token ceiling here would
    # be inventing a number, and it would be the wrong one for every model in
    # the registry at once.
    max_tokens: int | None = Field(default=None, ge=1)
```

`ge=1` and nothing else. `builder/registry.py:111-174` gates
`response_format`, `reasoning_effort` and tool-calling against the roster row
and **does not look at `max_tokens`** - correctly, because the number that would
bound it is per-model context, which is not what that function is for.
`budget.py` prices a call at the constant `GRAPH_BUDGET_CALL_COMPLETION_TOKENS`
(4253) rather than at `max_tokens`, so the estimate does not move either:
**$0.0225**, 2 modelled calls, 1 billable node (measured, in
`synthetic-check.txt`).

### The value reaches the wire

`builder/runtime.py:848-866` puts `max_tokens` into the `LLM(...)` keyword set
verbatim, and `:866` only *defaults* it when the author named nothing:

```python
    optional.setdefault("max_tokens", GRAPH_BUDGET_CALL_COMPLETION_TOKENS)
```

An author's own value wins - the comment beside it says so in as many words.

### The refusal, measured

**Measured** 2026-09-05 against the real OpenRouter endpoint with this
deployment's own key, and it costs nothing because nothing is generated. The
`provider.max_price` block is included because `openrouter_authored_params`
(`config.py:1206-1229`) always sends it for an authored node:

```text
$ POST https://openrouter.ai/api/v1/chat/completions
  {"model":"google/gemini-3.5-flash-lite","messages":[{"role":"user","content":"hi"}],
   "max_tokens":2000000000,"provider":{"max_price":{"prompt":1.0}}}

  -> status 400
  {"error":{"message":"This endpoint's maximum context length is 1048576 tokens. However,
   you requested about 2000000001 tokens (1 of text input, 2000000000 in the output).
   Please reduce the length of either one, or use the context-compression plugin to
   compress your prompt automatically.","code":400,...}}
```

400 is not in the OpenAI SDK's retry set, so there is one request and one
refusal. No generation, no tokens, no bill - the "near zero" PLAN.md budgets for
this run.

### The failure path, file:line

An authored node runs with `stream=True` (`builder/runtime.py:881-886`, and the
`Crew` half at `:689`), so the refusal surfaces in CrewAI's streaming path:

| # | file:line | what happens |
| --- | --- | --- |
| 1 | `crewai/llm.py:1117-1127` | `crewai_event_bus.emit(self, event=LLMCallFailedEvent(error=str(e), ...))` then `raise Exception(f"Failed to get streaming response: {e!s}") from e` |
| 2 | `events/serializer.py:618-619` | `LLMCallFailedEvent` becomes `FrameKind.LLM`, `stage: "error"`, with `call_id`, `model`, `error`, level `ERROR`. No `LLMCallCompletedEvent`, so **no token frame and no `cost_usd` movement** |
| 3 | `events/serializer.py:627-636` | `AgentExecutionErrorEvent` / `TaskFailedEvent` become `FrameKind.AGENT`, `stage: "error"`, level `ERROR` |
| 4 | `builder/runtime.py:1680-1704` | `_node_error_frame` with `error_class`, `message`, `attempt`, `will_retry`, `routed` |
| 5 | `service/registry.py:2770-2785` | one `FrameKind.ERROR` / `WORKFLOW_END` frame, `record.mark_failed(exc)`, run status **FAILED** |

`retry` is explicitly `{"max_retries": 0, "backoff_seconds": 0}` and `on_error`
is `"fail"`, so there is one attempt, no fallback model and no error edge -
which is what keeps the bill at zero and the trace at one refusal.

### Injections considered and rejected

- **A wrong OpenRouter key on the node** (`AuthoredAgentConfig.credential_id`,
  `AGENT_CREDENTIAL_KIND = "openrouter"` at `config.py:3074-3079`). This
  genuinely 401s - measured: `POST /v1/chat/completions` with
  `sk-or-v1-0000...` answers `401 {"error":{"message":"User not found.","code":401}}`
  - but it needs a vault row, and the vault is unreachable on this backend.
  Both halves are set out in `../builder-toolfail/inject.md` section 1:
  `credentials_api.py:118-127` requires an identity to create one, and
  `credentials.py:698-701` refuses to resolve any credential for an **unowned**
  run. It would also fail at `_agent_api_key` (`builder/runtime.py:2007-2027`)
  before the model was called, which is a node error rather than an LLM one.
- **`max_execution_time: 1`** - deterministic enough, but it abandons a call
  that has already started, so it bills and the failure is a timeout rather than
  a refusal.
- **`llm.timeout: 1`** - the same objection, plus the OpenAI SDK retries a
  timeout twice invisibly (`app-surface.md` section 5.4(3)), which makes the
  trace ambiguous about how many calls there were.
- **A guardrail that can never pass** - not expressible: `TaskConfig`
  (`builder/document.py:221-238`) has no guardrail field. `guardrail_max_retries`
  bounds retries of guardrails a *library* task declares in YAML, and this node
  is authored.

### The identifiers

The C2 invented-identifier row belongs to `builder-toolfail`; this graph does
not need it and deliberately does not reuse the same role. Its own names are
`Channel Sounder` (role) and `sound_the_channel` (node id and label), so a
frame from this run can never be confused with one from the other.

## 3. The request sequence on the paid backend

Anonymous throughout - no `Authorization`, no `X-Synthetic-User`, no credential
step.

```bash
BASE=http://127.0.0.1:8000
DOC=docs/observability/evidence/proof/builder-agentfail/document.json

# 1. validate. Expect 200 with valid=true, problems=[]
curl -sS -X POST "$BASE/api/builder/validate" -H 'content-type: application/json' \
     --data "{\"document\": $(cat $DOC)}"

# 2. create. Expect 201; keep .id (ug_xxxxxxxx) as $ID
curl -sS -X POST "$BASE/api/builder/workflows" -H 'content-type: application/json' \
     --data "{\"document\": $(cat $DOC)}"

# 3. publish. Expect 200 with gated_before_spend=true
curl -sS -X POST "$BASE/api/builder/workflows/$ID/publish"

# 4. launch, unattended. Expect 202, then a run that reaches status=failed
curl -sS -X POST "$BASE/api/sessions/proof-agentfail/runs" -H 'content-type: application/json' \
     --data "{\"workflow_id\":\"$ID\",\"inputs\":{\"idea\":\"the north reach of the estuary\"},\"gates\":\"auto\"}"
```

The same two rules as the other graph decide steps 3 and 4, and this document
satisfies both:

- **`gates` must be `"auto"`, and the graph must HAVE a gate.**
  `service/app.py:1679-1724` - 403 for an anonymous caller unless
  `VALIDATOR_ALLOW_AUTO_GATES` is set (it is, in `.env`), 422 if the workflow
  has no gates. `auto` sets the reserved `no_gates` state key and
  `builder/gates.py:162-166` answers it with `{"decision": "approve"}`.
  **`gates:auto` is what makes this unattended.**
- **The graph must be gated before it spends.** `service/app.py:1644-1661` -
  403 for an anonymous launch of a graph that bills before any gate, unless
  `BUILDER_ALLOW_GATELESS_GRAPHS` is set; it is not, and should stay unset.
  `start_sounding` sits between `the_brief` and `sound_the_channel`, so
  `gate_before_first_billable` (`builder/descriptor.py:452-482`) answers
  **true** - the publish response in `synthetic-check.txt` says
  `"gated_before_spend": true`.

**Cost.** Static estimate $0.0225. Actual expected spend **$0.00**: the one LLM
call is refused at 400 before generation, and there is no retry and no fallback
model. Confirm from the OpenRouter generation records that no generation exists
for this run - the absence is itself the evidence.

## 4. A2 / D5 - launching two runs at once

The concurrent-launch recipe and the `RUN_CONCURRENCY=2` evidence live once, in
`../builder-toolfail/inject.md` section 5. PLAN.md pairs `validator-live` with
`builder-toolfail`, not with this graph, so nothing here is needed for A2/D5.
If this graph is ever the second arm instead, note that it fails within one LLM
round trip, which makes it a poor concurrency probe: it may be finished before
the other run's first node starts.

## 5. What to record in `RUNS.md`

1. PLAN.md's stated injection - an unknown model id - is **refused at validate
   and at publish**, with two error-severity problems (section 1, measured).
   The substitute keeps the plan's failure CLASS (a provider refusal, zero
   tokens) and changes only which field carries it.
2. The exact provider message. It names the endpoint's context length, so it is
   evidence that the request reached OpenRouter's router and was refused there
   rather than locally.
3. Whether `cost_usd` stayed at 0.0 for the run, and whether a `token` frame was
   emitted at all. It should not have been - `events/serializer.py:618-619` emits no
   usage on a failed call - and that absence is worth asserting rather than
   assuming.
