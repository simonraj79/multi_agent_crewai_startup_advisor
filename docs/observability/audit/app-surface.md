# The application's instrumentation surface

**What this is.** A read-only audit of *where, inside this application, the
values an observability backend needs already exist*, and of how a Langfuse
exporter would attach to them. It changes nothing under `src/`, `tests/` or
`frontend/`, and installs nothing into `.venv`.

**Measured 2026-09-05 against `main` = `b65bd65`**, working tree clean apart
from this document and its evidence directory. CrewAI **1.15.18**, Python
**3.13.5** (both printed by `python -c "import crewai, sys; ..."`).

**Starting position, confirmed rather than assumed.** `grep -rn langfuse` over
`src/`, `tests/`, `frontend/src/` and `pyproject.toml` returns nothing, and
`uv.lock` contains no `langfuse` package. There is no Langfuse code in this
repository and the package is not installed. Everything below is about what an
exporter *would* attach to.

Every claim is cited `file:line`. Where a command was run its transcript is in
[`../evidence/audit/app/`](../evidence/audit/app/) and is cited by filename.

---

## 1. Run scoping

### 1.1 The mechanism: one ContextVar-scoped stream sink per run

The run identity inside a CrewAI callback is carried by **two** ContextVars in
`src/brief_crew/events/context.py`, set together by one context manager:

```python
ui_run_id: ContextVar[str | None] = ContextVar("brief_crew_ui_run_id", default=None)   # :16
current_capture: ContextVar[CaptureContext | None] = ...                                # :25
@contextmanager
def capture_events(context: CaptureContext) -> Iterator[CaptureContext]:                # :31
    run_token = ui_run_id.set(context.run_id)                                           # :34
    capture_token = current_capture.set(context)                                        # :35
    scope_token = current_node_scope.set(None)                                          # :41
    sink_token = add_stream_sink(context.adapter)                                       # :42
```

`CaptureContext` is a frozen dataclass of exactly `run_id` + `adapter`
(`events/context.py:19-22`). The sink itself is registered with CrewAI's own
`add_stream_sink`, which is also a ContextVar:

- `.venv/Lib/site-packages/crewai/events/stream_context.py:12` —
  `_stream_sinks: ContextVar[tuple[StreamSink, ...]] = ContextVar("crewai_stream_sinks", default=())`
- `:27-30` — `publish_stream_event` iterates `_stream_sinks.get()` and calls each
  sink **synchronously**, inline, on whatever thread raised the event.

So "which run is this" is not looked up: it is the identity of the sink object
that was invoked, and that object is `RunRecord.capture`, one per run
(`service/registry.py:929`, built in `__post_init__` at `:962-967`).

### 1.2 Where it is entered — exactly one place

```bash
grep -rn "capture_events" src/brief_crew --include=*.py
```

answers `service/registry.py:2694` and nothing else (plus the definition and the
`__init__` re-export). The whole of `RunRegistry._execute` runs inside it:

- `service/registry.py:2689` — `with scoped_hooks():`
- `:2690-2693` — `register_scoped(InterceptionPoint.PRE_STEP, ...)` (the cancel guard)
- `:2694-2695` — `with capture_events(CaptureContext(run_id=record.run_id, adapter=record.capture)):`
- `:2696-2707` — the runner (`runtime.runner(execution)`) or its `resume(...)`

**Consequence for an exporter, and it is the most important fact in this
section: a run launched from the CLI has no capture scope at all.** The console
scripts are `run_crew`, `kickoff`, `plot`, `validate`, `serve`
(`pyproject.toml:57-64`), and `validate` (`validator_flow.py:1252`) builds a
`ValidatorFlow` and kicks it off directly, never through `RunRegistry`. A CLI run
therefore emits no frames, has no `run_id`, and would be invisible to any
exporter attached to the frame spine. It *would* be visible to an exporter
attached to CrewAI's global event bus or to a global `before_llm_call` hook.

### 1.3 Propagation into CrewAI's worker threads

The service submits `_execute` to a `ThreadPoolExecutor`
(`service/registry.py:1460-1462`, `thread_name_prefix="brief-run"`; the `submit`
is at `:1904-1909`). A pool worker thread starts with an empty context, and
`capture_events` is entered **inside** `_execute`, on that thread — so the sink
belongs to that thread's context and nothing else.

From there CrewAI propagates it explicitly at every boundary that matters:

- **Sync flow methods**: `crewai/flow/runtime/__init__.py:2971-2972` —
  `ctx = contextvars.copy_context()` then
  `result = await asyncio.to_thread(ctx.run, method, *args, **kwargs)`.
- **Async tasks**: `:1191`, `:1199` — `asyncio.create_task(...)`, and a task
  copies the creating context.
- **Async task execution inside a Crew**: `crewai/task.py:617-618` —
  `ctx = contextvars.copy_context()` then `threading.Thread(target=ctx.run, ...)`.
- **Human-feedback step**: `crewai/flow/runtime/__init__.py:3540-3541` — again
  `ThreadPoolExecutor` + `copy_context()`.

`events/registry.py:53-60` states the same chain from this repository's side and
notes the proof: *"the stream sink itself is reached through a `ContextVar`, so
any event arriving here has already proved the chain holds."* That is correct —
an event that reaches `StreamSinkAdapter.__call__` is by construction running in
a context that inherited the sink.

### 1.4 Can two concurrent runs interleave in the sink? No — three independent reasons

1. **Different sinks.** Each run has its own `StreamSinkAdapter`
   (`registry.py:962`) with its own `FrameBuffer` (`:958-961`), and the sink is
   selected by context, not by lookup.
2. **`RUN_CONCURRENCY` defaults to 1** (`config.py:1270`), so by default only one
   run executes at a time anyway.
3. **Per-adapter lock.** `StreamSinkAdapter.__call__` holds `self._capture_lock`
   (`events/adapter.py:51`, taken at `:65`) across node-scope tracking,
   serialization, buffer push and notification — so the three parallel research
   branches of *one* run serialize against each other and the frame order the
   buffer sees is the order the adapter returned (`events/adapter.py:78-86`).

The per-run sequencing state is guarded by that same lock; `adapter.py:52-61`
says so explicitly and lists the three per-run fields it protects.

### 1.5 Resume after a gate — the run id survives, by identity

A gate pause is `HumanFeedbackPending`, caught in `_execute`
(`registry.py:2765-2767` → `_mark_pending`). The resume goes through the *same*
`_execute`, with the *same* `RunRecord`, and therefore the same `run_id`, the
same `capture` adapter and the same `FrameBuffer` (`registry.py:2696-2707`:
`resume(execution, context=context, feedback=feedback)`).

The two flow-level resumes:

- Validator: `service/runner.py:225-240` —
  `ValidatorFlow.from_pending(context.flow_id, execution.persistence, ...)` then
  `flow.resume(feedback)`.
- Builder: `service/builder_runner.py:202-216` —
  `Flow.from_pending(context.flow_id, execution.persistence, definition=self._flow_definition())`
  then `flow.resume(feedback)`.

`flow_id == run_id` for any resumable workflow (`registry.py:1616`:
`flow_id = run_id if hasattr(runtime.runner, "resume") else None`), so the CrewAI
flow uuid and the service run id are the *same string*. That is the single most
useful join an exporter has.

One thing an exporter must handle: **`Flow.resume()` emits a second
`FlowStartedEvent` for the same root flow.** `events/serializer.py:197-224`
(`FlowScope`) exists for exactly this, and claims the root flow *by name* so a
resumed run can still report finishing.

**After a process restart** the record is rebuilt by
`RunRegistry._restore_record` (`registry.py:3209-3239`) — same `run_id`, a
**new** `StreamSinkAdapter` and a **new** `FrameBuffer`, with the persisted
frames replayed back into it (`:3250-3258`). An exporter that keys a trace on
`run_id` is unaffected; one that keeps in-memory span handles is not, and would
have to rehydrate or start a second trace segment.

---

## 2. Identity — where role, task, crew, tool, node and model become available

### 2.1 The per-frame actor stamp — this is the crown jewel

`FieldBoundedSerializer.drafts` (`events/serializer.py:328-364`) is a wrapper
around the isinstance ladder whose *only* job is to say who spoke. It calls
`_actor(event)` (`:366-392`), which reads four first-class `BaseEvent` fields and
merges them into **every** frame the ladder produced:

```python
for source_attr, detail_key in (
    ("agent_role", "agent_role"),
    ("task_name",  "task_name"),
    ("agent_id",   "agent_id"),
    ("task_id",    "task_id"),
):                                                    # serializer.py:376-381
...
attempts = getattr(event, "run_attempts", None)       # :388-390
```

Those four fields are declared on CrewAI's own base event —
`.venv/Lib/site-packages/crewai/events/base_events.py:77-80` — and are populated
in `__init__` from `from_task` / `from_agent` (`base_events.py:101-116`, and
again for LLM events at `crewai/events/types/llm_events.py:16-27`).
`run_attempts` is on `ToolUsageEvent`
(`crewai/events/types/tool_usage_events.py:20`).

Frames on the `workflow` node are deliberately **not** stamped
(`serializer.py:358-363`) — run-level statements must not be attributed to
whichever agent happened to raise the triggering event.

### 2.2 Node id — the join CrewAI cannot make

`NodeRegistry.resolve` (`events/registry.py:341-378`) resolves in order:
`task_nodes` → `agent_role_prefixes` → `method_name` → CrewAI's
`current_flow_method_name` → **`current_node_scope`** (`:375-377`) → quarantine.

`current_node_scope` (`events/registry.py:67-69`) is this repository's own
ContextVar, written once per *declared* flow-method start from the sink
(`events/adapter.py:213-239`), inside the coroutine CrewAI is about to
`copy_context()` into the worker thread. `events/registry.py:33-66` records why a
nominal table would not work: `AgentExecutor` is itself a `Flow`, so at
`ToolUsageStartedEvent` time CrewAI's `current_flow_method_name` names
`execute_tool_action` / `execute_native_tool`, and the first paid run put **148
frames** on the quarantine node with per-node cost reading zero.

Frames that could not be placed land on the visible `unattributed` node
(`events/registry.py:15`) and are counted at push time
(`events/buffer.py:72-73`, surfaced as `frames.unattributed` in
`registry.py:1102-1106`).

### 2.3 Crew name, tool name, model name

- **Crew name**: `serializer.py:548-552` — `event.crew_name` on the three
  `CrewKickoff*` events. There is no `crew_id`; a crew node deliberately claims
  no agent role because several agents run there.
- **Tool name**: `serializer.py:470`, `:472-487`, `:488` — `event.tool_name`,
  plus `query` lifted from the arguments (`tool_query`, `:752-766`) and the
  tool's own reported query from its JSON envelope (`:480`, `tool_envelope` at
  `:768-802`).
- **Model name**: `serializer.py:491` (`event.model` on start) and `:493-528` (on
  completion), from `LLMEventBase.model`
  (`crewai/events/types/llm_events.py:12`). Note that `LLM.__new__` strips the
  `openrouter/` prefix for native providers, which is why
  `config.compute_cost_usd` resolves several spellings (`config.py:472-483`).
- **Static node identity for a builder graph**: `builder/descriptor.py:145`
  (`library_agent_role`), `:179-213` (`node_agent_role`), used at `:303`. For the
  two hand-written flows the same facts are in `service/graph.py:80-96`
  (`VALIDATOR_CREW_WIRING`, `BRIEF_CREW_WIRING`) — eight nodes with
  `crew` / `agent_role` / `task_name`.

### 2.4 Which CrewAI 1.15.18 event classes exist, and which the adapter handles

Enumerated by running the installed package, not from memory. Evidence:
[`crewai-event-classes.txt`](../evidence/audit/app/crewai-event-classes.txt) and
[`adapter-handled-vs-ignored.txt`](../evidence/audit/app/adapter-handled-vs-ignored.txt).

**163** `BaseEvent` subclasses are declared under
`.venv/Lib/site-packages/crewai/events/types/*.py`, across 21 modules. **36** of
them are handled by the isinstance ladder in
`events/serializer.py::_event_drafts`; **127** are ignored and merely counted by
`record_unhandled` (`serializer.py:651` → `:739-750`).

Handled (36), by module:

| module | handled |
| --- | --- |
| `agent_events.py` | `AgentExecutionStartedEvent`, `AgentExecutionCompletedEvent`, `AgentExecutionErrorEvent` |
| `crew_events.py` | `CrewKickoffStartedEvent`, `CrewKickoffCompletedEvent`, `CrewKickoffFailedEvent` |
| `flow_events.py` | `FlowStartedEvent`, `FlowFinishedEvent`, `FlowFailedEvent`, `MethodExecutionStartedEvent`, `MethodExecutionFinishedEvent`, `MethodExecutionFailedEvent`, `MethodExecutionPausedEvent`, `HumanFeedbackRequestedEvent`, `HumanFeedbackReceivedEvent` |
| `llm_events.py` | `LLMCallStartedEvent`, `LLMCallCompletedEvent`, `LLMCallFailedEvent`, `LLMStreamChunkEvent` |
| `llm_guardrail_events.py` | `LLMGuardrailStartedEvent`, `LLMGuardrailCompletedEvent` |
| `logging_events.py` | `AgentLogsExecutionEvent` |
| `mcp_events.py` | `MCPConnectionFailedEvent` |
| `skill_events.py` | `SkillLoadedEvent`, `SkillActivatedEvent`, `SkillUsedEvent`, `SkillLoadFailedEvent` |
| `task_events.py` | `TaskStartedEvent`, `TaskCompletedEvent`, `TaskFailedEvent` |
| `tool_usage_events.py` | `ToolUsageStartedEvent`, `ToolUsageFinishedEvent`, `ToolUsageErrorEvent`, `ToolValidateInputErrorEvent`, `ToolSelectionErrorEvent`, `ToolExecutionErrorEvent` |

Plus one repo-local event, `VerdictComputedEvent` (`events/verdict.py`,
dispatched at `serializer.py:446-447`).

**Ignored classes an exporter would actually want.** The full 127 is in the
evidence file; these are the ones that matter and why:

| ignored class(es) | why an exporter wants it |
| --- | --- |
| `LLMThinkingChunkEvent` (`llm_events.py`) | reasoning-token stream; the only per-token view of what the escalation tier is charging for. Sibling of `LLMStreamChunkEvent`, which *is* handled. |
| `ToolFailureDetectedEvent` (`tool_usage_events.py`) | a tool that ran and reported failure under a `warn` policy — today only visible as `failure` inside `ToolUsageFinishedEvent` (`serializer.py:474`). |
| `MCPToolExecutionStartedEvent` / `CompletedEvent` / `FailedEvent`, `MCPConnectionStartedEvent` / `CompletedEvent` (`mcp_events.py`) | only `MCPConnectionFailedEvent` is handled, so a *successful* MCP tool call is entirely invisible. For a graph whose tools are MCP servers, that is most of the trace. |
| `AgentReasoningStartedEvent` / `CompletedEvent` / `FailedEvent` (`reasoning_events.py`) | CrewAI's planning step; a natural span parent for the tool calls underneath it. |
| `MemoryQuery*` / `MemorySave*` / `MemoryRetrieval*` (10, `memory_events.py`) and `KnowledgeQuery*` / `KnowledgeRetrieval*` (7, `knowledge_events.py`) | retrieval spans — the RAG view Langfuse renders natively. Also the one place embedding work becomes visible, which `compute_cost_usd` structurally cannot see (§3.4). |
| `LiteAgentExecutionStartedEvent` / `CompletedEvent` / `ErrorEvent` (`agent_events.py`) | `Agent.kickoff()` outside a Crew raises these instead of `AgentExecution*`. |
| `CheckpointStarted/Completed/Failed` plus fork/restore (12, `checkpoint_events.py`) | would let a trace show a resume as a resume rather than as a second run. |
| `HookDispatchedEvent` (`hook_events.py`) | names which interception point fired — the cheapest way to see this app's own `PRE_STEP` cancel guard in a trace. |
| `StepObservation*`, `PlanStep*`, `GoalAchievedEarlyEvent` (10, `observation_events.py`) | plan-and-execute step boundaries. |
| `A2A*` (32, `a2a_events.py`), `Sig*` (5, `system_events.py`), `*Env*` (4), `CrewTest*` / `CrewTrain*` (8), `AgentEvaluation*` (3), `Conversation*` and `Flow{Created,Paused,Plot,Input*}` (11 of `flow_events.py`) | **not** wanted. Nothing in this product uses A2A, training, evaluation or conversational flows; exporting them would be noise. |

The honest summary: the adapter handles the *lifecycle* comprehensively and the
*retrieval* and *reasoning* families not at all.

---

## 3. Usage and cost

### 3.1 Where tokens are counted

Three layers, in order.

**(a) CrewAI extracts usage from the provider response.**
`.venv/Lib/site-packages/crewai/llms/providers/openai/completion.py:2720-2742`
(`_extract_openai_token_usage`) builds a **new dict with a whitelist of five
keys** — `prompt_tokens`, `completion_tokens`, `total_tokens`, and optionally
`cached_prompt_tokens` and `reasoning_tokens`. That dict is what reaches the
event (`:1929-1949`, `:2005-2008`).

**(b) The serializer normalizes and prices it.** `events/serializer.py:493-528`,
on `LLMCallCompletedEvent`, emits **three** frames — an `after` frame, an
`utterance` frame and a `TOKEN` frame:

```python
usage = dict(normalize_usage(event.usage or {}, completed_call=True))   # :495-497
cost_usd = compute_cost_usd(model, usage["prompt_tokens"], usage["completion_tokens"])  # :498-502
usage["cost_usd"] = cost_usd                                            # :515
```

`normalize_usage` (`:165-192`) resolves five alias families (`_USAGE_ALIASES`,
`:80-98`) and recurses up to depth 4 (`_usage_value`, `:135-162`). Cost is
written **both** at `details["cost_usd"]` and inside `details["usage"]`, and
`serializer.py:503-514` records exactly why: the Studio client narrows to
`details.usage` and had been reading `$0.0000` over a full token stream.

**(c) The registry accumulates it.** `RunRecord._record_usage`
(`service/registry.py:1223-1278`), driven from `_on_frames` on every
`FrameKind.TOKEN` frame (`:1186-1187`):

- run totals into `self.usage` (`:1256-1263`)
- per-`(node_id, model)` totals into `self.node_usage` (`:1269-1279`)
- `elapsed_ms` per call, from paired `before`/`after` LLM frames
  (`_track_llm_timing`, `:1207-1221`)
- `cost_usd is None` means *no price on file*, is never added as `0.0`, and logs
  one warning naming the model (`:1240-1252`)

### 3.2 What `LLMCallCompletedEvent` actually carries in 1.15.18

Read out of the installed package
(`.venv/Lib/site-packages/crewai/events/types/llm_events.py:89-112`):

```python
class LLMCallCompletedEvent(LLMEventBase):
    type: Literal["llm_call_completed"] = "llm_call_completed"
    messages: str | list[dict[str, Any]] | None = None
    response: Any
    call_type: LLMCallType
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    response_id: str | None = None
```

plus, inherited from `LLMEventBase` (`:9-13`): `model`, `call_id`, and (via
`BaseEvent`) `agent_role`, `agent_id`, `task_name`, `task_id`, `event_id`,
`parent_event_id`, `previous_event_id`, `triggered_by_event_id`,
`started_event_id`, `emission_sequence`, `timestamp`
(`crewai/events/base_events.py:69-87`).

So: **yes** to `response`, `usage`, `model`, `call_type`, `messages`.

### 3.3 The provider response id — it DOES survive, and the app already records it

This is the finding that most changes the picture.

- `response_id` is a declared field on `LLMCallCompletedEvent`
  (`llm_events.py:99`) and on `LLMStreamChunkEvent` (`:143`) and
  `LLMThinkingChunkEvent` (`:151`).
- It is populated from the raw provider response by
  `extract_choices_finish_reason_and_id`
  (`.venv/Lib/site-packages/crewai/llms/_finish_reason_utils.py:21-55`), which
  reads `response.id` — for OpenRouter's chat-completions API that is the
  `gen-...` generation id.
- The chat-completions path calls it at
  `crewai/llms/providers/openai/completion.py:1935-1937` and passes it into every
  `_emit_call_completed_event` on that path (`:1919-1921`, `:1947-1950`,
  `:1989-1992`, `:2005-2008`); the streaming path at `:2178`, `:2187`, `:2194`,
  `:2059-2073`, `:2102-2104`, `:2147-2149`.
- **This repository already writes it into a frame**: `events/serializer.py:525`
  puts `"response_id": event.response_id` on the LLM `after` frame.
- `config.py:1086-1089` already names the intended use: *"Reconcile against
  `get-generation` using the `response_id` the serializer records on every
  model-call frame."*

**What does NOT survive is the raw response object.** `_handle_completion` passes
`response=content` — a *string* — into the event
(`completion.py:1998-2007`), or `list(message.tool_calls)`, or a
`model_dump_json()`. The `ChatCompletion` object never leaves the provider
method. So an exporter can have the id and the token counts, but not the raw
payload.

### 3.4 `extra_body={"usage": {"include": True}}` — not set, and it would not help today

```bash
grep -rn "extra_body" .venv/Lib/site-packages/crewai/ --include=*.py
```

returns **only** `providers/anthropic/completion.py` (`:997`, `:1003`, `:1022`,
`:1147`, `:1153`, `:1181`, `:1545`, `:1551`, `:1570`, `:1683`, `:1689`, `:1715`),
which is a different provider entirely. Nothing on the OpenRouter path sets it.

`config.compute_cost_usd`'s own docstring says so (`config.py:488-497`) and is
correct as far as it goes:

> *"CrewAI never sets `extra_body={"usage": {"include": True}}` and
> `_extract_openai_token_usage` whitelists only token counts, so OpenRouter's own
> per-generation cost figure never reaches any event."*

Both halves check out. **And the second half is the binding one**: this
application *does* already send `extra_body` — `config.py:1185-1203`
(`openrouter_escalation_params`), `:1206-1229` (`openrouter_authored_params`),
`:1232-1240` (`openrouter_reasoning_params`), reaching the wire through
`additional_params` (`completion.py:1800`,
`params.update(self.additional_params)`). So adding `"usage": {"include": True}`
is one dict key away. It would still be discarded by
`_extract_openai_token_usage`'s five-key whitelist (`completion.py:2720-2742`)
before any event saw it — so on its own it buys nothing. **The reachable route to
real cost is the `response_id` above, resolved out of band against OpenRouter's
`get-generation`.**

### 3.5 Where the app exposes its own figures for reconciliation

| surface | where | carries |
| --- | --- | --- |
| `GET /api/runs/{run_id}` | `service/models.py:535-577` (`RunStatusResponse`) | `usage` (`UsageMetrics`, `:518-527`), `node_usage` (`list[NodeUsage]`, `:530-532` — adds `node_id` + `model`), `frames` counters, `result`, `verdict`, `error`, `stop_reason`, `mode` |
| in-memory source | `service/registry.py:1082-1124` (`status_payload`), `:1127-1131` (`node_usage_payload`) | the same, sorted by `(node_id, model)` |
| `run_node_metrics` table | `service/persistence.py:186-200` | PK `(run_id, node_id, model)`; `successful_requests`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `call_count`, `elapsed_ms`, `cost_usd NUMERIC(12,6)`, `updated_at`. Written by `registry.py:3117-3130` |
| `runs` table | `persistence.py:135-178` | `usage` JSON, `captured_frames`, `dropped_frames`, `frame_gaps`, `emit_errors`, `subscriber_dropped` |
| `GET /api/runs/{run_id}/frames` | `registry.py:2632-2657` (`all_frames`), over `replay_frames` (`:2608-2631`) | the ring / replayed frames |
| `GET /api/runs/{run_id}/logs?format=ndjson\|zip` | `service/app.py:1971-2022` | ndjson of every frame; the zip additionally contains `run.json` (the whole `RunStatusResponse`) and `node-metrics.json` |
| live `metrics` frame | `registry.py:1133-1187` (`emit_metrics`) | coalesced run totals, per-node breakdown and capture counters, emitted on change and at `run_completed` / `run_failed` / `run_cancelled` |

There is also a reconciliation the app already performs against CrewAI's own
totals: `RunRegistry._log_usage_reconciliation` (`registry.py:3132-3160`) diffs
event-derived usage against the flow's returned `UsageMetrics` and logs a warning
on any delta. That is the exact shape a Langfuse-versus-app reconciliation would
take, one layer out.

**A frame carries `response_id` but no surface aggregates it.** There is no
`generation_ids` list on the run row and no index from `response_id` to
`(run_id, node_id)`. Recovering it today means scanning the NDJSON export for
`details.stage == "after"` on `kind == "llm"` frames.

---

## 4. Per-call request shaping — can a run id go on the wire?

Four seams exist, and this repository already uses two of them.

### 4.1 `additional_params` → `extra_body` (already in use; the recommended route)

`BaseLLM.additional_params` is a declared field
(`.venv/Lib/site-packages/crewai/llms/base_llm.py:190`) and *also* the sink for
any unknown kwarg (`:283-289`). It is merged into the request at
`crewai/llms/providers/openai/completion.py:1800`
(`params.update(self.additional_params)`) for chat completions and `:861` for the
Responses API. `extra_body` is the accepted OpenAI-SDK kwarg for
provider-specific JSON, which is why this repository puts reasoning effort and
the price ceiling there (`config.py:1003-1010` explains the mechanism;
`:1173-1240` are the four builders).

Call sites that already pass it:
`crews/validator_crew/validator_crew.py:354` and `:409` (Synthesist, Reporter);
`builder/runtime.py:887` (every authored node).

### 4.2 `default_headers` (unused; the cleanest for a correlation id)

`OpenAICompletion.default_headers: dict[str, str] | None`
(`completion.py:224`) is passed straight to the OpenAI client
(`_get_client_params`, `:417`). The OpenRouter provider config already sets one
(`HTTP-Referer`) and **merges** user headers over it
(`providers/openai_compatible/completion.py:50`, `:230-251`). So
`LLM(model=..., default_headers={"X-Langfuse-Trace-Id": run_id})` is legal and
would reach OpenRouter on every request from that LLM.

`grep -rn "default_headers" src/brief_crew --include=*.py` returns nothing — the
app does not use it today.

### 4.3 CrewAI hooks — `before_llm_call` / `PRE_MODEL_CALL`

`crewai/hooks/` exists in 1.15.18 with `before_llm_call` / `after_llm_call`
decorators and register/unregister functions (`hooks/__init__.py:4-31`,
`hooks/decorators.py:89-124`). The context object (`hooks/llm_hooks.py:29-113`,
`LLMCallHookContext`) exposes `executor`, `messages` (mutable, in place),
`agent`, `task`, `crew`, `llm`, `iterations`, `response`.

Two registration scopes, and both are already used by this codebase or by CrewAI:

- **Global**: `brief_crew/builder/max_iter.py:117-127` registers
  `nudge_trailing_model_turn` once per process via
  `register_before_llm_call_hook`. Its module docstring (`:28-64`) is a
  ready-made argument for why this is the right seam and why subclassing `LLM` is
  not — `LLM.__new__` is a factory that returns `OpenAICompatibleCompletion` and
  ignores `cls`.
- **Run-scoped**: `crewai/hooks/dispatch.py:101-103` is a ContextVar registry;
  `scoped_hooks()` (`:160-175`) and `register_scoped()` (`:177-183`) enter and
  populate it. `RunRegistry._execute` **already opens exactly such a scope**
  (`service/registry.py:2689-2692`) for the `PRE_STEP` cancel guard. Scoped
  `PRE_MODEL_CALL` hooks are honoured for agent calls at
  `crewai/utilities/agent_utils.py:1968-1985`
  (`*get_scoped_hooks(InterceptionPoint.PRE_MODEL_CALL)`), and for direct calls at
  `crewai/llms/base_llm.py:1023-1046`.

So an exporter can register a **per-run** LLM-call hook on the line after the
existing cancel guard, with no new plumbing at all.

### 4.4 When are LLM objects constructed — per process or per run?

**Per run, at the moment the node executes.** This is the fact that makes baking
a run id into `extra_body` viable.

- **Validator**: each `@agent` method constructs a fresh `LLM(...)` inside
  `Agent(...)` — `crews/validator_crew/validator_crew.py:344-359` (Synthesist),
  `:404-414` (Reporter). Those methods are reached only through the crew
  factories, which build the crew per call: `validator_flow.py:158-183`
  (`_scope_runner` … `_report_runner`, each `SomeCrew().crew()`), wired into
  `ValidatorCrewFactories` (`validator_flow.py:186-196`) and called from the flow
  methods.
- **Builder**: `DefaultCrewFactories.agent_crew` builds `Agent(llm=LLM(...))`
  inline (`builder/runtime.py:596-660`, the `LLM(...)` at `:636`), and
  `_authored_agent` (`:693`) → `_authored_llm` (`:822-891`, the `return LLM(...)` at `:881-891`).
  The factory itself is selected per run through a ContextVar
  (`builder/runtime.py:947-961`, `use_crew_factories`), entered by
  `BuilderFlowRunner.__call__` at `service/builder_runner.py:138`.
- No `lru_cache` or module-level singleton anywhere on these paths:
  `grep -rn "lru_cache|functools.cache"` over the crews, `validator_flow.py` and
  `builder/runtime.py` returns exactly one hit — `builder/runtime.py:360`, which
  caches *YAML parsing*, not an `LLM`.

Because construction happens on a thread whose context already carries
`ui_run_id` and `current_capture`, `additional_params` (or `default_headers`)
could be populated from the run's own context with no signature change anywhere.

### 4.5 The seam this repository built and never used

`events/context.py:16` declares `ui_run_id`, `capture_events` sets and resets it
(`:34`, `:49`), and `events/__init__.py:10` and `:60` export it. And:

```bash
grep -rn "ui_run_id" src/brief_crew --include=*.py
```

returns only the definition, the two set/reset lines and the two export lines —
**nothing reads it**. It is a declared, run-scoped, thread-propagated run id with
no consumer. An exporter is its consumer.

---

## 5. Unhappy paths

### 5.1 A failed agent

| where it surfaces | frame today |
| --- | --- |
| `AgentExecutionErrorEvent` | `serializer.py:538-540` — `FrameKind.AGENT`, `stage: "error"`, `task`, `error`, level `ERROR` |
| `TaskFailedEvent` | `serializer.py:545-547` — `FrameKind.AGENT`, `stage: "error"`, `error`, level `ERROR` |
| `MethodExecutionFailedEvent` | `serializer.py:462-464` — `FrameKind.NODE_STATE` / `NODE_END`, `stage: "error"`, `error`, plus `error_class` when the exception declares one (`error_class_of`, `:263-276`) |
| the flow method raising out of the runner | `registry.py:2740-2760` — one `FrameKind.ERROR` / `WORKFLOW_END` frame on the `workflow` node, `record.mark_failed(exc)` (`registry.py:1176-1180`), run status `FAILED`, `error` clipped to 4096 chars |
| a builder node, per attempt | `builder/runtime.py:1679-1704` (`_node_error_frame`) — `error_class`, `message`, **`attempt`**, **`will_retry`**, `fallback_model`, **`routed`** |

**What an exporter needs beyond this**: nothing for the *fact* of failure. What is
missing is the **stack** — only `str(exc)` and the class name are recorded
(`_error_class`, `builder/runtime.py:1622-1633`), never a traceback. A Langfuse
span would end with `level=ERROR` and a one-line message.

### 5.2 A raising tool

Four distinct paths, all handled:

- `ToolUsageErrorEvent` → `serializer.py:488-490`: `stage: "error"`, `tool`,
  `query`, `error`, level `ERROR`.
- `ToolValidateInputErrorEvent` / `ToolSelectionErrorEvent` /
  `ToolExecutionErrorEvent` → `serializer.py:586-597`, each with a distinct
  English reason (*"rejected the agent's arguments"*, *"was requested but does
  not exist"*, *"failed during execution"*).
- A tool that *ran* and reported failure: `ToolUsageFinishedEvent.failure` →
  `serializer.py:472-487`, level `WARNING`, with `failure` on the frame.
- A tool that returns this repository's JSON envelope reports its own status:
  `tool_envelope` lifts `status` → `tool_status`, plus `query`, `result_count`,
  `notes`, `retrieved_at` (`serializer.py:100-113`, `:768-802`). The producers set
  `"rate_limited"` / `"failed"` / `"empty"` / `"ok"` —
  `tools/market_research.py:181-200`, `:241-244`, `:283-285`, `:318`, `:335`;
  `tools/hn_sentiment.py:435`; `tools/github_feasibility.py:393`.

Whether a tool exception *escapes* the step is a policy: `warn` (CrewAI's
default, kept) versus `raise`, set per node — `builder/runtime.py:626-631`.

### 5.3 A cancelled run — and a run killed by `MAX_RUN_COST_USD`

Both arrive by the **same** path and are told apart by one field.

Cancellation is cooperative at a `PRE_STEP` boundary. Three guards raise the same
`HookAborted`:

- `RunRegistry._cancel_guard` (`registry.py:2775-2779`), registered scoped at
  `:2690-2692`;
- `RunExecution.checkpoint` (`service/runner.py:58-63`);
- the builder's per-node `checkpoint` (`builder/runtime.py:228-244`), which exists
  because a graph of only transforms and routers has no agent step to intercept
  (`:167-173`).

`_execute` catches it once (`registry.py:2711-2739`):

```python
budget_stop = record.stop_reason == COST_CEILING_REASON              # :2722
details = {"status": "cancelled"}                                    # :2723
if budget_stop:
    details["reason"] = COST_CEILING_REASON                          # :2725
    details["cost_usd"] = float(record.usage.get("cost_usd", 0.0))   # :2726
    details["ceiling_usd"] = float(record.max_cost_usd)              # :2727
```

then emits one `RUN_STATE` / `WORKFLOW_END` frame at level `WARNING`, calls
`record.mark_cancelled()` and `record.emit_metrics("run_cancelled")`.

The ceiling itself is `_enforce_cost_ceiling` (`registry.py:1283-1352`), called
from `_record_usage` (`:1267`). It deliberately **does not raise and emits no
frame** (`:1298-1307`): it runs inside a CrewAI event handler while
`StreamSinkAdapter.__call__` holds a non-reentrant lock, so it sets
`cancel_requested` and lets the next `PRE_STEP` abort. `MAX_RUN_COST_USD`
defaults to `10.0` (`config.py:1489`).

**So an exporter does see a terminal signal**, and a good one: a `RUN_STATE` frame
with `status: "cancelled"`, `reason`, `cost_usd`, `ceiling_usd`, followed by a
`metrics` frame. What it does *not* see is the abort at the CrewAI level —
`HookAborted` propagates as a plain exception and raises no event.

### 5.4 A retried LLM call

Three different retries, with three different visibilities:

1. **Guardrail retries — fully visible, with a count.**
   `LLMGuardrailStartedEvent` / `CompletedEvent` carry `retry_count`
   (`crewai/events/types/llm_guardrail_events.py:31`, `:69`), and
   `serializer.py:562-570` puts `retry_count`, `guardrail`, `guardrail_type`,
   `success` and `error` on a `FrameKind.GUARDRAIL` frame. `serializer.py:554-561`
   records why this branch exists: a rejected report regenerates on the escalation
   tier and produced a second run of token frames with nothing saying why.
2. **The builder's own node retries — visible, and richer than CrewAI's.**
   `_retry_frame` (`builder/runtime.py:1711-1725`) emits `attempt`, `of`,
   `backoff_ms`, `model`; `_node_error_frame` (`:1679-1704`) emits `attempt`,
   `will_retry`, `routed`, `fallback_model`. `_is_retryable` (`:1608-1619`) is the
   classifier, over `{408, 425, 429, 500, 502, 503, 504}` (`:1605`).
3. **The OpenAI SDK's own transport retries — completely invisible.**
   `OpenAICompletion.max_retries: int = 2` (`completion.py:223`) is passed to the
   client (`_get_client_params`, `:416`). Those retries happen inside the SDK's
   HTTP layer: no CrewAI event, no frame, no token frame. A 429 retried twice and
   then succeeding looks like one call that took a long time.

`run_attempts` on tool events (`tool_usage_events.py:20`) is stamped onto every
frame by `_actor` (`serializer.py:388-390`) — `serializer.py:389` calls it *"the
answer to 'why did this tool fire three times'"*.

### 5.5 A gate pause

`HumanFeedbackRequestedEvent` → `serializer.py:465-466` (`FrameKind.GATE_OPEN`,
`gate_id`, `options`, `output`); `MethodExecutionPausedEvent` →
`serializer.py:572-573` (`NODE_PAUSED`). The service adds `GATE_EXPIRED` and
`GATE_ALERT` frames from the sweeper (`registry.py:1955-1995` and following).

**For an exporter this is the hardest case**: a paused run is *not* finished, the
worker thread has returned, and the resume may arrive minutes later or never. A
trace must either stay open across the pause or be modelled as two segments
joined by `run_id`.

### 5.6 Summary — what an exporter would need to end a trace legibly

Everything terminal is already emitted on the `workflow` node with an explicit
`status` in `details`:

- completed — `serializer.py:429-431` (`status: "completed"`, `result`)
- failed (flow) — `serializer.py:432-439` (`FrameKind.ERROR`, no `status`, `error` present)
- failed (runner) — `registry.py:2740-2760`
- cancelled / budget-stopped — `registry.py:2728-2739`
- final reconciled totals — `emit_metrics("run_completed" | "run_failed" | "run_cancelled")`,
  `registry.py:2762`, `:2758`, `:2737`

The gap is the **interrupted** run: a process that dies mid-method emits nothing.
The orphan sweep (`VALIDATOR_ORPHAN_RUN_RECOVERY`) fixes the *row* on the next
boot, but no frame is emitted at the moment of death, so an exporter would leave a
dangling trace until it applied its own timeout.

---

## 6. Redaction policy already in force

### 6.1 The one list, and both walks that apply it

`src/brief_crew/events/redaction.py` is the single source. Its docstring (`:1-66`)
records that `persistence.py` redacted and `serializer.py` did not, so the
database was clean while the live socket, `/frames` and the NDJSON export were
not.

- **Exact names** (`SECRET_KEYS`, `:88-131`), matched on a normalized key —
  lower-cased, non-alphanumerics dropped (`normalize_secret_key`, `:148-149`):
  `accesstoken`, `apikey`, `authorization`, `ciphertext`, `clientsecret`,
  `cookie`, `dburi`, `dsn`, `env`, `headervalue`, `headers`, `nonce`, `password`,
  `privatekey`, `refreshtoken`, `secret`, `setcookie`, `token`, `xapikey`.
- **Suffixes** (`SECRET_KEY_SUFFIXES`, `:136`): a normalized key ending in `key`,
  `token`, `secret`, `password` or `dsn`, provided something precedes it
  (`is_secret_key`, `:152-162`).
- **Two carve-outs**: `STRUCTURAL_KEY_NAMES = {"bodykey"}` (`:145`), and any raw
  key starting with `out__` (`BUILDER_STATE_SLOT_PREFIX`, `:140`) — a builder
  node's own output slot.
- The marker is `REDACTED = "***"` (`:86`).

Applied on the way to the ring at `events/serializer.py:310-314`, inside `clip`,
so it covers the live socket, `/frames`, the NDJSON and the ZIP.

`headers` is redacted **wholesale** (`redaction.py:48-51`) rather than walked, and
`env` likewise (`:104-110`) — an MCP stdio server's whole environment block.

### 6.2 What is refused by *bounding* rather than by naming

`SerializerLimits` (`serializer.py:245-261`): `max_string=4096`, `max_key=128`,
`max_items=64`, `max_depth=4`, `max_repr=512`, `max_tool_output=1_048_576`,
`max_tool_field=512`. Plus `MAX_UTTERANCE_CHARS = 4096` (`config.py:1534`),
`MAX_FRAME_PREVIEW_CHARS = 2048` (`:1538`), `MAX_NODE_ERROR_CHARS = 1024`
(`:1542`), and `MAX_IDENTIFIER_LENGTH` for every id.

And a tool's `results` array is **never** recorded — `tool_envelope`
(`serializer.py:768-781`) lifts only the five-field diagnostic head, keeping
`result_count` and `output_chars` instead. The reason is stated at `:100-104`: a
single market envelope carries ten scraped page bodies against a 2,000-frame ring.

### 6.3 What is NOT recorded at all today — the starting content policy

**Prompts are never recorded.** `LLMCallStartedEvent` carries `messages`
(`llm_events.py:45`) and the serializer takes only `call_id` and `model`
(`serializer.py:491-492`). `LLMCallCompletedEvent` also carries `messages` (`:93`)
and again it is not read (`serializer.py:493-528`). This is the single biggest
policy difference an exporter would introduce: Langfuse's default value
proposition *is* prompt/completion capture.

**Completions ARE recorded**, bounded: the `utterance` frame carries
`text[:MAX_UTTERANCE_CHARS]` plus a `truncated` flag (`serializer.py:526`), and
`LLMStreamChunkEvent` carries every chunk (`:531-532`, coalesced at
`adapter.py:113-134` on `STREAM_CHUNK_COALESCE_MS = 250`, `config.py:1546`).

### 6.4 Where user text and credentials could still leak

- **The idea.** `FlowStartedEvent` puts `inputs` on the run's opening `RUN_STATE`
  frame (`serializer.py:427`), and the user's idea is in there. It is bounded
  (2000 chars by `MAX_RUN_INPUT_CHARS`) but not redacted — deliberately, since the
  console reads it back. It also sits in `runs.inputs` (`persistence.py:166`) and
  in `RunHistoryEntry`.
- **Tool arguments.** `ToolUsageStartedEvent` → `args: self.clip(event.tool_args)`
  and `input_preview: self._preview(event.tool_args)` (`serializer.py:470`). The
  clip redacts by key name; the preview goes through `clip` first — and
  `serializer.py:670-687` records that **until 2026-09-04 it did not**, so a
  builder agent's Firecrawl key (held as a pydantic *field*,
  `FirecrawlSearchTool.api_key`) landed in `details.input_preview` in plaintext
  while `details.args` beside it read `***`. That is the shape of leak to watch
  for: one walk redacting and one not.
- **Credential values.** Resolved into a constructor argument and dropped —
  `builder/runtime.py:632-637` says the string *"lives in this constructor call
  and nowhere this module could log it"*, and `ResolvedCredential`'s `repr` hides
  its plaintext (`service/credentials.py:342-351` —
  `fields=<{len} ***>`). A failure carries an `error_class`
  (`credential-not-yours`, `service/credentials.py:165`), never a value.
- **Anything a model says.** The `utterance` frame is unfiltered model output up
  to 4 KiB. If an agent echoes a key it was given, it is on the frame.

**The policy an exporter should inherit, stated plainly:** redact by key name
using `events.redaction.is_secret_key` (never a second list); bound every string;
never send tool `results`; treat prompt capture as a *new* decision rather than an
extension of the existing one; and put every value through one walk, not two.

---

## 7. Lifecycle — where a Langfuse client would live, and the pattern to copy

### 7.1 Where it would be created and flushed

`create_app` (`service/app.py:650-661`) is the only constructor, and it already
has a FastAPI `lifespan` (`:762-770`):

```python
@asynccontextmanager
async def lifespan(app: Any):
    yield
    if owns_registry:
        registry.close()          # :768
    if owned_store is not None:
        owned_store.close()       # :770
```

`registry.close()` (`registry.py:2658-2667`) stops the gate sweeper, shuts the
executor down with `wait=True`, and closes the frame writer. A Langfuse client's
`flush()` / `shutdown()` belongs beside those two `close()` calls, **after** them,
so nothing is still emitting.

`app_from_env()` (`app.py:2404-2415`) is the factory `serve()` hands uvicorn by
name (`:2417-2431`), and is where `SYNTHETIC` is read. `synthetic=True` must not
disable the exporter — the synthetic path is the free proof run and the one place
an exporter can be exercised without spending money — but it *should* mark the
trace, because a synthetic run's usage frames are fabricated
(`service/runner.py:882-948`, `_token_usage`) and would otherwise pollute cost
dashboards with `CHEAP_MODEL` numbers that were never billed.

The three startup assertions (`app.py:675-677`) are the precedent for a fail-loud
config check. **A Langfuse exporter must not join them.** Those three guard money
and secrets; observability being misconfigured must never refuse to boot.

### 7.2 The pattern the exporter must copy: bounded queue, drop counters, never raise

The frames pipeline is a worked example of "telemetry that cannot fail a run",
and the exporter should be built the same way.

**(a) The producer never blocks and never does I/O.**
`_PersistenceWriter.enqueue` (`registry.py:718-722`) is a single `put_nowait` onto
a `Queue(maxsize=VALIDATOR_PERSIST_QUEUE_CAPACITY)` (`:711`, capacity 4096 at
`config.py:520`). A `Full` becomes `self.on_error(run_id)` — never an exception.
The class docstring (`:680-693`) states the contract: *"no database work, no lock
the database can hold, no blocking."*

**(b) A separate daemon thread does the work**, batching on whichever of size or
time comes first — `VALIDATOR_FRAME_BATCH_SIZE` frames, or
`VALIDATOR_FRAME_FLUSH_INTERVAL_SECONDS = 0.25` (`config.py:3175`) since the batch
opened (`registry.py:758-793`). `_write` (`:795-813`) turns any exception into
`on_error` per run.

**(c) A bounded shutdown.** `flush()` (`:724-742`) posts a marker and waits with a
timeout, explicitly *"bounded on purpose: a caller must never hang because the
writer thread is gone"*. `close()` (`:744-757`) is idempotent.
`_release_stragglers` (`:815-830`) drains what will never be written and accounts
for it through the same `on_error`, so a shutdown-time loss stays visible.

**(d) Losses are counted, never silent.** `FrameBufferStats`
(`events/buffer.py:18-31`) carries `captured`, `dropped`, `gaps`, `emit_errors`,
`unattributed`; the ring counts an eviction as both a drop and a gap
(`buffer.py:74-76`); `note_emit_error` (`:87-89`) is bumped by
`_note_persistence_error` (`registry.py:3091-3099`), which deliberately does
**not** call `require()` because *"a counter bump is never worth a database read
on the writer thread"*. Every counter reaches `GET /api/runs/{id}`
(`registry.py:1094-1108`) and the durable row (`persistence.py:169-173`).

**(e) Every emit path is total.** `StreamSinkAdapter.__call__` wraps everything in
`try/except Exception: self.buffer.note_emit_error()` (`adapter.py:63-73`);
`emit` does the same (`:252-269`); `_notify` too (`:271-277`).
`builder/runtime.py:1636-1680` (`_emit_frame`) is the same discipline from the
runtime side, with the sentence an exporter should adopt verbatim: *"a run that
died because its telemetry did would be the worst possible trade."*

**(f) The subscriber queue drops the OLDEST, not the newest.**
`FrameSubscription._publish_on_loop` (`registry.py:862-869`) evicts the head when
full and counts the drop. A Langfuse batch queue should make the same choice, and
say which end it drops.

**One trap the exporter must respect, and it is measured.**
`_enforce_cost_ceiling`'s docstring (`registry.py:1298-1307`) explains that code
reached from `_on_frames` runs **while `StreamSinkAdapter._capture_lock` is
held**, and that lock is a plain non-reentrant `threading.Lock`
(`adapter.py:51`). An exporter hooked into `on_frames` therefore must not emit a
frame, must not block, and must not take any lock the capture path also takes.
`put_nowait` onto its own queue is the only safe shape.

---

## 8. Feasibility of the `langfuse` SDK

Evidence:
[`langfuse-install-feasibility.txt`](../evidence/audit/app/langfuse-install-feasibility.txt).

### 8.1 Which version, and what it would pull in

`./.venv/Scripts/python.exe -m pip index versions langfuse` answers
`No module named pip` — **the project venv has no pip**. `uv` 0.7.19 is the tool
here, and `uv.lock` is committed.

```
$ uv pip install --dry-run --python .venv/Scripts/python.exe langfuse
Resolved 26 packages in 388ms
Would download 2 packages
Would install 2 packages
 + langfuse==4.15.1
 + wrapt==2.4.0
```

**Two packages.** `langfuse` 4.15.1 and `wrapt`. Everything else it needs is
already installed at a satisfying version. Declared requirements, read from the
wheel's `METADATA` (fetched with `uv pip install --target <scratchpad>/lf
--no-deps`, i.e. into the scratchpad and **not** into `.venv`):

| requirement | installed today | satisfied |
| --- | --- | --- |
| `httpx>=0.15.4,<1.0` | 0.28.1 | yes |
| `pydantic>=2,<3` | 2.12.5 | yes |
| `backoff>=1.10.0` | 2.2.1 | yes |
| `wrapt>=1.14,<3` | — | **new** |
| `packaging>=23.2,<27.0` | 26.3 | yes |
| `opentelemetry-api>=1.33.1,<2` | 1.42.1 | yes |
| `opentelemetry-sdk>=1.33.1,<2` | 1.42.1 | yes |
| `opentelemetry-exporter-otlp-proto-http>=1.33.1,<2` | 1.42.1 | yes |
| `typing-extensions>=4.12.2,<5` | installed | yes |

`Requires-Python: >=3.10, <4.0` against this project's `>=3.10,<3.14` and Python
3.13.5 — compatible.

For contrast, a *clean* resolution (`uv pip compile`, no existing environment)
picks `opentelemetry-* 1.44.0`, `opentelemetry-semantic-conventions 0.65b0`,
`pydantic 2.13.5`, `protobuf 7.36.1`. That is what a from-scratch `uv sync` would
land on — a bump of the OTel stack the environment already has, not a conflict.

### 8.2 Conflicts

`uv pip check --python .venv/Scripts/python.exe` today:
`Checked 162 packages in 2ms / All installed packages are compatible`. Nothing is
broken before the change, so a regression would be attributable.

**OpenTelemetry is already installed** — CrewAI ships it: `opentelemetry-api`,
`-sdk`, `-proto`, `-semantic-conventions` and **both** the OTLP gRPC and HTTP
exporters, all at 1.42.1 / 0.63b1. langfuse needs only the HTTP exporter, which is
present.

### 8.3 Install path

`uv add langfuse`, and it should go under a **new optional-dependency extra**
rather than into the base `dependencies`. `pyproject.toml:16-41` declares base
dependencies (`crewai[tools]`, `firecrawl-py`, `pinecone`, `cohere`, `requests`,
`python-dotenv`, `pydantic`, `pyyaml`); `:43-56` declares the `service` extra
(FastAPI, uvicorn, sqlalchemy, psycopg, pyjwt). A Langfuse exporter is a *service*
concern — the CLI paths have no capture scope at all (§1.2) — so either extending
`service` or adding an `observability` extra keeps `git clone && python -m
unittest` free of a network SDK. `uv.lock` is committed and must move in the same
commit.

### 8.4 CrewAI's own telemetry and tracing — would they collide?

Two separate systems, and **neither collides**.

**(a) `crewai.telemetry` (OTel, anonymous usage).** It builds its own
`TracerProvider` (`crewai/telemetry/telemetry.py:134`) and **deliberately does not
install it globally**. `set_tracer` (`:172-190`) says so at length:

> *"Deliberately does not install a global TracerProvider. Doing so made every
> OTel-instrumented library in the host process ... resolve `trace.get_tracer()`
> to our provider and export to our collector ... It also meant that when an
> application had already installed its own provider, our spans were created by
> theirs and went to their collector instead of ours."*

Spans are created from `self.provider` directly. Disabled by `OTEL_SDK_DISABLED`,
`CREWAI_DISABLE_TELEMETRY` or `CREWAI_DISABLE_TRACKING` (`:163-168`).

**(b) langfuse's provider.** `_init_tracer_provider`
(scratchpad `langfuse/_client/resource_manager.py:647-689`) installs a global
provider **only if the current one is a `ProxyTracerProvider`** — i.e. only if
nothing has registered one. Since CrewAI registers none, langfuse would install
the global provider and CrewAI would keep its private one. No double reporting and
no capture of the other's spans, in either direction.

**(c) `CREWAI_TRACING_ENABLED` is a different thing entirely** — it drives
CrewAI's *own* trace listener on the event bus
(`crewai/events/listeners/tracing/trace_listener.py`), resolved by
`should_enable_tracing` (`crewai/events/listeners/tracing/utils.py:108-137`),
which posts to CrewAI's backend and is unrelated to OTel. Note the trap the code
confirms: there is **no branch returning `False`** for the env var — `"false"`
fails the `("true", "1")` test at `:128-131` and falls through to stored consent
at `:133-135`. A process with a stored `trace_consent` has CrewAI tracing on
regardless of that variable.

---

## 9. Flows available for Task 3 proof runs

### 9.1 What is runnable, and how

| flow | HTTP | CLI | tools |
| --- | --- | --- | --- |
| **Brief Flow** (`brief-flow`) | `POST /api/sessions/{id}/runs` with that `workflow_id` (`app.py:1401-1413`); runner `BriefFlowRunner` (`runner.py:198-205`) | `kickoff` → `brief_crew.main:kickoff`; `run_crew`; `plot` (`pyproject.toml:59-62`) | Firecrawl scrape (`crews/brief_crew/scrape_tool.py`), Pinecone + Cohere via `brief_crew.embeddings` |
| **Idea Validator** (`idea-validator`) | same endpoint; runner `ValidatorFlowRunner` (`runner.py:208-240`), resumable | `validate --idea "..."` → `brief_crew.validator_flow:validate` (`validator_flow.py:1252-1277`) | Firecrawl search/scrape (`tools/market_research.py`), HN Algolia (`tools/hn_sentiment.py`), GitHub search (`tools/github_feasibility.py`) |
| **Any published builder graph** | same endpoint, `workflow_id` = the published graph id; runner `BuilderFlowRunner` (`builder_runner.py:88-139`), resumable | none | whatever the author attached — the tool registry is `builder/tools.py`, with `credential_kind` per entry (`:575-710`) |

The free backend is `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5 PORT=8099`;
`app_from_env()` reads `SYNTHETIC` (`app.py:2404-2415`) and swaps in
`SyntheticRunner` / `SyntheticValidatorRunner` (`app.py:735-740`) and
`SyntheticCrewFactories` for the builder (`builder_runner.py:786`).

### 9.2 Three ways to make an agent fail deliberately, engine-neutral

Each changes **nothing** about flow semantics or model routing, and each exercises
a different failure class. What the app records today is given for each, because
that is what the reconciliation compares against.

**(A) A builder-authored graph whose agent holds a tool with an invalid
credential — a *tool* failure.**
Publish a one-agent graph with, say, `firecrawl_search` attached and a credential
whose `api_key` is a syntactically valid but wrong string, stored through
`POST /api/builder/credentials`. `_firecrawl` (`builder/tools.py:401-412`)
constructs the tool with that key; Firecrawl answers 401/402 and the tool raises
or returns a `"failed"` envelope.

*Recorded today:* a `FrameKind.TOOL` frame at `stage: "error"` with `tool`, `query`
and `error` (`serializer.py:488-490`), or a `WARNING` `after` frame with
`tool_status: "failed"` and `notes` (`serializer.py:472-487`,
`market_research.py:181-200`). Then the node's own `_node_error_frame` with
`error_class`, `attempt`, `will_retry`, `routed` (`builder/runtime.py:1679-1704`).
Run status depends on the node's `tool_failure_policy`
(`builder/runtime.py:626-631`) and on whether an error edge exists.
*Cost:* the agent's LLM call before the tool call is billed; the tool call itself
is free. This is the cheapest of the three.

**(B) A builder agent node given a model the API rejects — a *provider* failure.**
An authored agent node's model comes from the registry
(`builder/runtime.py:822-891`, `return LLM(model=model, ...)` at `:881`). A model whose
cheapest endpoint is over `MODEL_PRICE_CEILING_IN` is filtered out by
`provider.max_price` (`config.py:1173-1183`, sent via `openrouter_authored_params`,
`:1206-1229`) and **OpenRouter fails the request rather than overspending** —
`config.py:1135-1144` says so and names `openai/o4-mini` as the measured example.
Publishing such a node is refused at the registry door, so the realistic version is
a model id the catalogue no longer serves.

*Recorded today:* `LLMCallFailedEvent` → an `LLM` frame at `stage: "error"` with
`call_id`, `model` and `error` (`serializer.py:529-530`); no token frame, so
`usage` does not move; then `_node_error_frame` and, if retries are exhausted, the
run-level `FrameKind.ERROR` frame and `status: failed` (`registry.py:2740-2760`).
*Cost:* zero tokens on the failing call. Note §5.4(3): the SDK retries a 5xx twice
invisibly first.

**(C) One deliberately wrong `FIRECRAWL_API_KEY` in the environment for one
validator run — a *branch* failure inside a real paid run.**
The market tool reads the key at call time — `tools/market_research.py:241`,
`api_key = os.getenv("FIRECRAWL_API_KEY")`, answering `status="failed"` with a
sentence when it is absent (`:244`). The other two branches (HN needs no key,
GitHub's `GITHUB_TOKEN` is optional — `github_feasibility.py:333`) run normally.

*Recorded today:* the market branch's tool frame carries `tool_status: "failed"`,
`notes` and `result_count`; the branch completes with empty findings; the
Synthesist scores over two branches instead of three; the run **completes** rather
than failing, with a low-confidence verdict. This is the most interesting arm for a
reconciliation, because it is a *partial* failure that the run status alone does
not show — you have to read the frames.
*Cost:* a full paid validator run minus the Firecrawl calls.

**And one free control, which should be run first.** The builder's synthetic
factories already inject typed failures from the environment:
`SyntheticCrewFactories.__init__` reads `SYNTHETIC_FAILURE` and
`SYNTHETIC_FAILURE_NODE` (`builder_runner.py:689-695`) and raises one of
`SyntheticRateLimitError` (`error_class = "rate_limit"`, `:293`),
`SyntheticRefusal` (`"refusal"`, `:305`), `SyntheticBadCredential` (`"auth"`,
`:321`), `SyntheticToolTimeout` (`"tool_timeout"`, `:335`) or
`SyntheticMalformedOutput` (`"schema"`, `:350`) — from the *factory*, because that
is where a real credential refusal and a bad model id land (`:697-717`). This
exercises the whole failure-frame path at zero cost and should validate the
exporter before any money is spent.

---

## 10. Concurrency

### 10.1 Between runs

`RunRegistry` owns one `ThreadPoolExecutor(max_workers=max_workers,
thread_name_prefix="brief-run")` (`registry.py:1460-1462`), where `max_workers`
defaults to `RUN_CONCURRENCY` (`:1380-1381`), itself
`int(os.getenv("RUN_CONCURRENCY", "1"))` (`config.py:1270`). Admission is bounded
separately by `MAX_QUEUED_RUNS = 8` (`config.py:1414`) because CPython's pool
queues submissions without limit (`registry.py:295-297`).

Each run's `_execute` enters `scoped_hooks()` and `capture_events(...)` on its own
pool thread (`registry.py:2689-2695`). A pool thread starts with an empty context,
and both context managers reset on exit, so a reused thread cannot inherit the
previous run's sink. `capture_events` additionally resets `current_node_scope` to
`None` at `events/context.py:41`, and `:36-40` records the exact defect that guards
against: *"a second run on a reused thread would inherit the last node the previous
run entered."*

### 10.2 Within one run — the three research branches

The validator's three branches are sibling `@listen("scope_approved")` methods.
CrewAI runs them as sibling asyncio tasks, each of which `copy_context()`s before
`asyncio.to_thread` (`crewai/flow/runtime/__init__.py:2971-2972`), so each branch
gets a **snapshot** of the run's context — the sink, `ui_run_id`, and the node
scope its own `MethodExecutionStartedEvent` wrote. `events/registry.py:62-66`
states the consequence: *"a task copies its context at creation, so a branch cannot
overwrite a sibling's node."*

Everything a branch starts inherits that snapshot: `Crew.kickoff()`, the nested
`AgentExecutor` flow, and `Task.execute_async`'s own `copy_context()` +
`threading.Thread(target=ctx.run, ...)` (`crewai/task.py:617-618`).

### 10.3 Where per-run trace state has to live

Three tiers, and an exporter needs all three:

1. **Per-run, context-propagated**: the trace id. `ui_run_id`
   (`events/context.py:16`) is exactly this and already exists, set at `:34` and
   reset at `:49`. Anything read inside a CrewAI callback must come from a
   ContextVar, not from a module global.
2. **Per-node-within-a-run, context-propagated**: the span parent.
   `current_node_scope` (`events/registry.py:67-69`) is exactly this and is already
   written per declared method start (`adapter.py:213-239`). A branch's spans
   should hang off its own node's span, and this is the only value that knows
   which.
3. **Per-run, shared and mutable**: the span handles themselves. These cannot live
   in a ContextVar — a branch's copy would not be visible to the parent — so they
   belong in a per-run object keyed by `run_id`, the way `RunRecord` and
   `StreamSinkAdapter` already are, with a lock. The natural home is the adapter
   itself, whose per-run mutable state is already documented as such
   (`adapter.py:46-61`) and already guarded by `_capture_lock` (`:51`).

**What keeps two runs from interleaving is therefore not a filter but an
identity**: the sink object invoked *is* the run. An exporter that copies that
shape cannot interleave; one that keeps a module-level "current trace" will, the
first time `RUN_CONCURRENCY` is raised above 1.

---

## Attachment points, ranked

### 1. `StreamSinkAdapter.on_frames` — RECOMMENDED

`service/registry.py:966` wires `on_frames=self._on_frames`; the adapter calls it
at `events/adapter.py:271-277`.

**Why.** It is the one place where run id, node id, agent role, task name, tool
name, model, token counts, cost, `response_id`, `call_id`, error class, retry
attempt and gate state are *all* already resolved, bounded, redacted and totally
ordered by `seq`. Everything hard about instrumenting CrewAI — the
`AgentExecutor`-is-a-Flow attribution problem (`events/registry.py:33-66`), the
nested-flow lifecycle problem (`serializer.py:197-224`), the token-alias problem
(`serializer.py:80-98`) — is already solved on the far side of it. Nothing in the
frame contract names an agent role, a task or a tool, so it generalises to flows
that do not exist yet by construction.

**Cost.** `_on_frames` runs while `StreamSinkAdapter._capture_lock` is held
(`registry.py:1298-1307` documents this, and it is a plain non-reentrant `Lock`,
`adapter.py:51`). The exporter must therefore be a `put_nowait` onto its own
bounded queue with its own daemon thread — precisely `_PersistenceWriter`
(`registry.py:680-830`). Copy that class; do not invent a second pattern.

**What it does not see.** CLI runs (§1.2), and prompts (§6.3) — because the
serializer never records them. Prompt capture needs a second, separate attachment
(3 below), and is a policy decision rather than a plumbing one.

### 2. `RunRegistry._execute` — the trace boundary

`service/registry.py:2669-2774`. This is where a trace should be **opened and
closed**, because it is the only place that sees the whole run including its
terminal state and the `HookAborted` / exception branches. Concretely: start the
trace just inside `capture_events` (`:2694`), and end it in each of the four exits
— `HookAborted` (`:2711`), `Exception` (`:2740`), `HumanFeedbackPending` (`:2765`,
which *suspends* rather than ends), and completion (`:2769`).

### 3. `register_scoped(InterceptionPoint.PRE_MODEL_CALL, ...)` — the prompt seam

`service/registry.py:2690-2692` already opens a `scoped_hooks()` context and
registers one scoped hook. A second `register_scoped` on the line below would give
a **per-run** LLM-call hook that sees `context.messages`, `context.agent`,
`context.task`, `context.llm` and `context.iterations`
(`crewai/hooks/llm_hooks.py:29-113`), honoured for agent calls at
`crewai/utilities/agent_utils.py:1968-1985` and for direct calls at
`crewai/llms/base_llm.py:1023-1046`. Use this **only** if prompt capture is wanted;
it is the only route to it, and `builder/max_iter.py:28-64` is the in-repo
precedent for the seam being sound.

### 4. `LLM(additional_params={"extra_body": ...})` / `default_headers` — the wire

`config.py:1173-1240` already assembles `extra_body`, and
`crews/validator_crew/validator_crew.py:354`, `:409` and `builder/runtime.py:887`
already pass it. Because LLMs are built per node execution inside the run's context
(§4.4), a run id could be baked in from `ui_run_id`. Use this **only** if
OpenRouter-side correlation is needed: it puts a run id in a third party's logs,
and the one `provider` key inside `extra_body` is already contended
(`config.py:1196-1200`). `default_headers` (`completion.py:224`, merged at
`openai_compatible/completion.py:230-251`) is the cleaner of the two and is unused
today.

### 5. A global `crewai_event_bus` listener — NOT recommended

`events/listener.py` already has one (`UIEventListener`, `:67-77`) and it is
documented *"opt-in safety net; do not combine with the primary stream sink"*
(`:68`). Its handlers are async and run outside the flow method's context, so
`current_node_scope` is unreadable and every frame degrades to the quarantine node
(`events/adapter.py:227-232`). It would, however, be the only way to see a CLI run.

### 6. `crewai.telemetry` — NOT an attachment point

It never installs a global provider (`crewai/telemetry/telemetry.py:172-190`), so
there is nothing to intercept. Listed only so nobody spends an afternoon
discovering it.

---

## What the app can know that OpenRouter cannot

OpenRouter sees one HTTP request, one model, one token count, one generation id.
Everything below exists only inside this process.

- **The run.** A `run_id` (`registry.py:1579`, a uuid4) grouping every call, tool,
  gate and retry — and the same string is the CrewAI `flow_id`
  (`registry.py:1616`), so a resume joins to its original.
- **The graph node.** Which of the 14 validator nodes, or which author-drawn
  builder node, a call belongs to (`events/registry.py:341-378`) — including which
  of three *concurrent* branches, which OpenRouter cannot distinguish because they
  are three simultaneous requests from one IP.
- **The agent and the task.** `agent_role`, `agent_id`, `task_name`, `task_id`,
  stamped on every frame (`serializer.py:366-392`) from CrewAI's own event fields.
- **The crew.** `crew_name` (`serializer.py:548-552`), and statically
  `service/graph.py:80-96`.
- **Whether a call was a tool call or an answer.** `LLMCallType`
  (`crewai/events/types/llm_events.py:31-35`).
- **Tools.** Which tool ran, with what query, returning how many results, in how
  many milliseconds, from cache or not, and its own reported status
  (`serializer.py:470-490`, `tool_envelope` at `:768-802`). OpenRouter never sees a
  Firecrawl, HN or GitHub call at all.
- **Why a call happened again.** `run_attempts` on tool events
  (`serializer.py:388-390`), `retry_count` on guardrail events (`:562-570`), and
  `attempt` / `will_retry` / `of` / `backoff_ms` on builder retry frames
  (`builder/runtime.py:1679-1725`). A guardrail rejection is a *whole task re-run*
  on the escalation tier; from OpenRouter it is indistinguishable from a second
  unrelated request.
- **The human.** Gate opened, gate answered, what was replied, gate expired, gate
  alerted (`serializer.py:465-468`; `registry.py:1955-1995`) — and therefore the
  wall-clock a run spent waiting for a person rather than for a model.
- **The owner.** `user_id` (`registry.py:879-885`, `persistence.py:139-155`).
- **Cancellation and why.** `stop_reason` distinguishing an operator's Cancel from
  `MAX_RUN_COST_USD` (`registry.py:2722-2739`), with the cost and the ceiling on
  the frame.
- **The deliverable and the score.** The `ValidationReport` body and the
  deterministic `Verdict` — score, confidence, band, `decision_reason`, fatal
  floors (`events/verdict.py`, `serializer.py:836-864`, `models.py:560`).
- **Per-node, per-model cost.** `run_node_metrics` keyed
  `(run_id, node_id, model)` (`persistence.py:186-200`) — OpenRouter can total a
  key, never a node.
- **What was lost.** `captured` / `dropped` / `gaps` / `emit_errors` /
  `subscriber_dropped` / `unattributed` (`events/buffer.py:18-31`), so a trace can
  say how complete it is.
- **The un-instrumented spend.** The app knows that embeddings, Cohere rerank and
  Firecrawl raise no `LLMCallCompletedEvent` and are absent from every dollar
  figure (`registry.py:1319-1326`) — OpenRouter cannot know they happened at all.
- **The generation id, joined to all of the above.** `response_id`
  (`serializer.py:525`) is the one field both sides hold, which makes it the
  reconciliation key rather than a curiosity.

---

## Evidence index

| file | what it is |
| --- | --- |
| [`crewai-event-classes.txt`](../evidence/audit/app/crewai-event-classes.txt) | every `BaseEvent` subclass declared under `crewai/events/types/` in the installed 1.15.18, by module — 163 total. Script source and output. |
| [`adapter-handled-vs-ignored.txt`](../evidence/audit/app/adapter-handled-vs-ignored.txt) | the 36 handled by `events/serializer.py::_event_drafts` and the 127 ignored, computed by parsing the serializer's `isinstance` ladder with `ast`. Script source and output. |
| [`langfuse-install-feasibility.txt`](../evidence/audit/app/langfuse-install-feasibility.txt) | `pip index versions` (no pip), `uv --version`, `uv pip install --dry-run` against the venv, `uv pip compile` isolated tree, `uv pip check`, the installed OTel/pydantic/httpx versions, and langfuse 4.15.1's `Requires-Dist`. |
