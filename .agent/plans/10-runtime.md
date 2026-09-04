# 10 — Runtime

Execution service, streaming, cancel, cost. Written 2026-09-02 against
`25634c0`. Owns contracts **C6** (frames) and **C7** (run API). Consumes C3,
C4, C5, C10, C11, C12.

## Problem

A published graph already runs through the one `RunRegistry`, the one frame
spine, the same durable gates and the same `$10` ceiling as the hand-written
flows (`builder_runner.py:92-136`, `registry.py:1266-1335`,
`runtime.py:142-156`). Four things about that path are wrong for a graph a
user authored, and none of them is visible from the canvas:

1. **The agent LLM is `LLM(model=…)` and nothing else** (`runtime.py:414`): no temperature, no `max_tokens`, no timeout. The budget prices every call at 4,253 completion tokens (`config.py:1895`) while nothing caps a completion. The validator's own branches pin both (`validator_crew.py:155-159`); the builder path does not.
2. **The completed model response is dropped** by the serializer (`events/serializer.py:472` emits `finish_reason` and `response_id` only) and every stream chunk is dropped by the client (`useValidatorRun.ts:973`). A run view cannot show what an agent said.
3. **A failing step fails the run.** There is no retry, no fallback model, no error port, and a run that dies at node 7 of 9 can only be started again from node 1.
4. **A run is a run.** There is no test mode, no dry run, no single-node execution, and no way to read the flow state at a step.

## Scope

The eleven entrypoints' construction of `Agent` / `Task` / `Crew` / `LLM`
from authored `with:` blocks with credentials resolved at run time; retry,
backoff and fallback inside the entrypoint; `replay_output`; the five frame
additions and per-node input/output previews; the run API additions; the
serializer changes; streaming; rehydration against the v2 schema.

## Out of scope

- Compiling. `09-compiler.md` owns the definition; this plan owns what happens after `Flow.from_declaration`.
- Admission control, rate limiting and the 413/422/429 ladder (CLAUDE.md §9) — unchanged and reused.
- Any new column that is not additive and nullable (`persistence.py:533-546`).
- Reconciling cost against OpenRouter's own per-generation figure (`get-generation`) — the generation-id capture is remaining-work item 41 and stays open.

## Design

### D1 — The entrypoint constructs the primitives; nothing else does

`run_agent` (`runtime.py:612-644`) gains the authored branch: when `with:`
carries `role`, it builds

```python
llm = LLM(model=llm["model"], api_key=resolve_credential(llm["credential_id"]) or platform_key, temperature=…, max_tokens=…, …, stream=True)
agent = Agent(role=…, goal=…, backstory=…, llm=llm, tools=[…], mcps=[…], skills=[…], max_iter=…, …)
task = Task(description=…, expected_output=…, agent=agent, output_json=<model from output_schema>, markdown=…, async_execution=…)
crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, stream=True)
```

through the same `_factories()` seam (`runtime.py:487-488`) that
`SYNTHETIC=1` swaps wholesale (`builder_runner.py:177-206`), so the
free-path double sees the authored fields too. `max_tokens` is always set —
default `GRAPH_BUDGET_CALL_COMPLETION_TOKENS` (4,253) so the priced call and
the real call agree for the first time. `Agent.llm` is never left `None`
(it resolves to OpenAI — `docs/crewai-notes.md` §1); the startup
`openrouter/` assertion (CLAUDE.md, platform rules) is extended to every
model id in the registry snapshot at boot. `reasoning_effort` goes through
`openrouter_reasoning_params` (`config.py:821-829`) because CrewAI drops the
kwarg for every non-o1 model (`config.py:707-712`).

`run_crew`'s authored branch builds each member the same way and
`Crew(agents=members, tasks=[…in task_order], process=…, manager_llm=…,
manager_agent=members[i], memory=…, cache=…, max_rpm=…, planning=…,
planning_llm=…)`. CrewAI refuses hierarchical without a manager
(`crew.py:729`); bounds refuse it first (C8 `crew-hierarchical-needs-manager`)
so the refusal has a node id.

### D2 — Credentials resolve inside the entrypoint, from a ContextVar, and die with it

`builder_runner.__call__` sets `current_run_user` (a ContextVar beside
`current_cancel_flag`, `runtime.py:126-139`) for the duration of `kickoff`
and `resume`. `resolve_credential(credential_id)` (C4) reads it, loads the
row scoped to that user, decrypts, and returns the plaintext to the
constructor. The plaintext is held by the tool or `LLM` object for the life
of the step and is never written to state, a frame, a log or the run row.
`_SECRET_KEYS` (`persistence.py:71-86`) gains `api_key`, `headers`,
`authorization`, `env`. A credential that does not exist or belongs to
someone else raises inside the step and surfaces as `node_error` with
`error_class = credential-not-yours`; the run does not name whose it was.

### D3 — Retry, backoff and fallback run inside the step

```text
for attempt in range(max_retries + 1):
    model = primary if attempt < max_retries or fallback is None else fallback
    checkpoint(node_id)                      # cancel + ceiling at every attempt
    try: return execute(model)
    except RetryableError as e:              # LLMCallFailed, tool timeout, rate limit
        emit node_error(attempt, will_retry=attempt < max_retries)
        if attempt < max_retries: emit retry(attempt+1, backoff_ms); sleep(backoff * 2**attempt)
raise
```

Rationale: a retry that re-enters a Flow method would depend on CrewAI
re-firing a listener, which is the mechanism closed item 35 worked around.
Inside the step it is a loop, `checkpoint` keeps cancel and the ceiling
honest per attempt (`runtime.py:142-156`, `registry.py:1266-1335`), and
every attempt's token frames land on `frame.node_id` so `_record_usage`
(`registry.py:1206`) bills it. The fallback model is the last attempt only.
What counts as retryable is a closed list in `runtime.py`: `LLMCallFailedEvent`
shapes, `ToolExecutionFailedError`, HTTP 429/5xx from a tool, MCP transport
errors. A guardrail failure, a malformed structured output and a model
refusal are **not** retried here — CrewAI's own `guardrail_max_retries`
already loops those with the agent's LLM (`docs/crewai-notes.md` §2).

### D4 — `on_error: route` catches, records, returns

The step method for a routed node wraps D3's loop in one more `try`: on
final failure it writes `err__<node> = {error_class, message}` and
`out__<node> = None`, emits `node_error(will_retry=False)`, and **returns
normally** so the paired router (09 D3) fires `e{i}_error`. The exception is
not re-raised. A run whose only failing node is routed reaches `completed`.

### D5 — `replay_output` seeds state and emits as if it had run

`runtime:replay_output(node_id, source)` writes `out__<node>` from the
source run's last `flow_states` row (`persistence.load_state`,
`persistence.py:623`, keyed by the source run's `flow_id`) or from the saved
test input (C7), emits `NODE_START` / `NODE_END` frames with
`details.replayed = true` so the console can draw it dimmed, and returns.
The source run must be **the caller's** (`require_own_run`,
`app.py:756-776`) and its state must contain the key; a missing key fails
the replay node with `node_error(error_class = replay-missing-output)`.

### D6 — Frames: five additions, all as `details.stage` discriminators

`FrameKind` (`events/models.py:20`) already has `LLM`, `EDGE_TAKEN`,
`ERROR`, `NODE_STATE`, `RUN_STATE`. The five C6 additions are new
`details.stage` values on **existing** kinds, so `run_frames.kind`
(`persistence.py:185-200`), the ring, the replay cursor and the client's
kind switch need no new enum member. Serializer changes:

- `LLMCallCompletedEvent` (`serializer.py:472`): additionally emit the `utterance` frame with `event.response` clipped to 4,096 characters (`crewai/events/types/llm_events.py:90` carries `response: Any` and `messages`).
- `LLMStreamChunkEvent` (`serializer.py:478`): unchanged, still clipped, still forwarded; the client stops dropping it (11).
- `MethodExecutionStartedEvent`: when the runtime's `current_predecessor` ContextVar names the method that emitted the trigger, emit `edge_traversal` first.
- `ToolUsageStartedEvent` / `FinishedEvent`: add `input_preview` / `output_preview` (≤ 2,048), extending the existing `query` / `result_count` capture (CLAUDE.md §8).
- `NODE_END`: add `output_preview` from `out__<node>` (≤ 2,048).

### D7 — Streaming is on for builder runs

`Crew(stream=True)` and `LLM(stream=True)` emit `LLMStreamChunkEvent` per
token. The ring is 2,000 frames and subscriber queues 512 (CLAUDE.md §8), so
a chatty authored agent could evict its own history. Chunks are therefore
**coalesced** in the serializer into one frame per 250 ms per `call_id`
before entering the ring, and the `utterance` frame at completion carries
the whole (bounded) text regardless — the dialogue rail (11) renders from
chunks while streaming and settles on the utterance.

### D8 — The run API gains modes, and `dry_run` creates nothing

`CreateRunRequest` (`service/models.py:125`, `gates` at `:162`) gains
`mode`, `test_input_id`, `node_id`, `resume_from`. `mode = dry_run` answers
**200** with `{valid, problems, budget, definition}` from the same
parse → bounds → budget → compile path, writes no `runs` row, holds no
admission slot and emits no frame — it is `POST /validate` plus the
compiled artifact and is free. `test` and `node_test` create a real run with
`runs.mode` set (additive column, `_ADDITIVE_COLUMNS`,
`persistence.py:547-549`), pass the same admission
(`app.py:1061-1096` — the gateless-graph 403 and the stale-ceiling 422
included), the same rate limit, the same ceiling and the same frames.
`resume_from` and `node_test` build the derived plan (09 D7) and run it as a
new run whose row records `resume_from` in `inputs`.

### D9 — Cancel, carve-outs, orphans, rehydration: unchanged and re-tested

`HookAborted` at every `checkpoint` (`runtime.py:142-156`) and at the
registry's `PRE_STEP` hook; a ceiling stop sets `stop_reason` and calls
`mark_cancelling()` without raising (`registry.py:1266-1335`); both reach
`cancelled` (`registry.py:2567-2592`). A WAITING run holds no slot
(`registry.py:1496`) and `answer_gate → _submit` cannot raise
`RunAdmissionError` (`registry.py:1612, 1830`); test runs inherit both.
Orphan recovery (`test_restart_recovery.py`, 22 tests) and boot rehydration
(`builder_rehydrate.py:95-199`) are re-run against v2 documents; a v1 row
is upgraded on the way out (15) and a row that no longer compiles under the
new bounds is skipped with the compiler's own sentence, as today
(`:134-143`).

## Interfaces

### C7 — run API (owned)

`POST /api/sessions/{session_id}/runs` body additions:

| field | type | default | notes |
| --- | --- | --- | --- |
| `mode` | `run \| test \| dry_run \| node_test` | `run` | `dry_run` returns 200 and no run |
| `test_input_id` | `str \| null` | `null` | a `builder_test_inputs` row of the caller's (15); required for `node_test` |
| `node_id` | `str \| null` | `null` | required for `node_test` |
| `resume_from` | `{run_id, node_id} \| null` | `null` | the run must be the caller's and terminal |

`dry_run` response: `{valid: bool, problems: [BuilderProblem], budget: BuilderBudget, definition: dict}`.
Other modes: unchanged `RunSnapshot` (`models.py:398` carries `result`), plus `mode` and `resume_from`.

`GET /api/runs/{run_id}/state?step=<seq>`: `{run_id, step, state: dict}` — the
flow state as of frame `seq` (the latest `flow_states` row at or before that
frame's timestamp; `persistence.py:101-110`), reserved keys included,
credential-bearing keys redacted. Owner-only (404 otherwise).

`GET /api/builder/workflows/{id}/compiled?version=`: the preview object from
09 D8. Owner-only.

Additive column: `("runs", "mode", "VARCHAR(16)")`, default `'run'` in the
model, nullable in the table.

### C6 — frames (owned)

All frames keep the v1 envelope (`seq, ts, kind, event_type, level, node_id, message, details, duration_ms`).

| name | `kind` | `event_type` | `details` |
| --- | --- | --- | --- |
| `utterance` | `llm` | `MODEL_CALL` | `stage: "utterance", call_id, agent_role, task_name, text (≤4096), truncated: bool, prompt_tokens, completion_tokens, model` |
| `edge_traversal` | `edge_taken` | `EDGE_PROCESS` | `stage: "traversal", from, to, port` |
| `node_error` | `error` | `NODE_END` | `stage: "error", error_class, message (≤1024), attempt, will_retry: bool, fallback_model \| null, routed: bool` (`level = ERROR`) |
| `retry` | `node_state` | `NODE_START` | `stage: "retry", attempt, of, backoff_ms, model` |
| `stage` | `run_state` | `NODE_START` | `stage: "plan", index, of, label, node_ids: []` — one per topological layer, all emitted at kickoff |
| chunk | `llm` | `MODEL_CALL` | `stage: "chunk"` — unchanged shape, coalesced per 250 ms |
| replay | `node_state` | `NODE_START` / `NODE_END` | `replayed: true` |
| previews | existing tool / node frames | — | `input_preview`, `output_preview` (≤2048) |

Frames never carry a credential value; `_SECRET_KEYS` is the guard and
`tests/events/test_secret_redaction.py` seeds a sentinel to prove it.

### Consumed

C3 (model ids and prices for `_record_usage`; `compute_cost_usd` returns
`None` for an unknown model, never `0.0` — `config.py:197-219`), C4
(`resolve_credential`), C5 (the `with:` shapes), C10 (`runs.mode`,
`builder_test_inputs`), C11, C12.

## Acceptance criteria

1. `tests/service/test_builder_runner.py::AuthoredAgentTests`: an authored agent node runs under `SYNTHETIC=1` and the synthetic factory receives `role`, `goal`, `backstory`, `task`, `llm` and the folded attachment lists; a real `Agent` constructed from the same `with:` block by `DefaultCrewFactories` has `llm.model`, `llm.max_tokens`, `llm.temperature` set and `llm.stream is True` (constructed, not kicked off — no cost).
2. `tests/service/test_run_result_and_cost.py`: `LLM.max_tokens == GRAPH_BUDGET_CALL_COMPLETION_TOKENS` by default, and a run's `usage.cost_usd` is priced per registry model, `None` for an unknown one.
3. `tests/service/test_credentials_runtime.py`: `resolve_credential` returns the plaintext only under `current_run_user`; another user's id yields `credential-not-yours`; a sentinel secret appears in no frame, no `flow_states` row, no `runs` row, no NDJSON export.
4. `tests/service/test_retry.py`: with `SYNTHETIC_FAILURE=rate_limit` on node `b` and `retry {max_retries: 2, backoff_seconds: 0, fallback_model}`, the run emits `node_error ×3`, `retry ×2`, the third attempt uses the fallback model, and the run completes; with `max_retries: 0` it fails at the first attempt; cancel between attempts reaches `cancelled`.
5. `tests/service/test_error_routing.py`: `on_error: route` on a node that fails completely → `e{i}_error` fires, the error-port successor runs, the run reaches `completed`, and `err__<node>` is in state; `on_error: fail` → the run reaches `failed` with the same `node_error` frame.
6. `tests/service/test_replay.py`: `resume_from {run_id, node_id: c}` on a failed `a → b → c` run emits replay frames for `a`, `b` with `replayed: true`, runs `c` for real, and the result equals a clean run's; a source run owned by another user → 404; a missing state key → `replay-missing-output`.
7. `tests/service/test_run_modes.py`: `dry_run` answers 200 with a definition, creates no `runs` row, increments no rate-limit bucket, emits no frame; `test` creates a row with `mode = test`; `node_test` without `test_input_id` → 422; `GET /state?step=` returns the state at that seq and 404 for another user's run.
8. `tests/events/test_utterance_frames.py`: `LLMCallCompletedEvent` with a 10,000-char response yields one `utterance` frame with `truncated: true` and 4,096 chars; chunks are coalesced to ≤ 4 frames per second per `call_id`; `edge_traversal` precedes the successor's `NODE_START` in `seq`; `stage` frames equal the plan's layer count.
9. `tests/service/test_additive_migration.py`: `runs.mode` is added to a table that already shipped and a pre-existing row reads `NULL` → `'run'`.
10. `tests/service/test_builder_rehydration.py`: a v1 row rehydrates through the upgrade; a v2 row naming a model no longer in the registry is skipped with `model-unknown` in the log and the process boots.
11. `tests/service/test_restart_recovery.py` still passes; a `test`-mode run interrupted mid-method is failed at startup like any other.
12. Streaming: with `SYNTHETIC=1 SYNTHETIC_BRANCH_DELAY_SECONDS=5`, `npx playwright test e2e/visual/run-canvas.spec.ts` still passes (the visual baseline is unchanged by frames it does not render).

Rubric dimensions answered: 11 (with 09), 12 (with 12), 13 (the boot
assertion over registry ids), 14 (credential scoping), 10's "alive" half of
rubric 10 depends on C6 landing.

## References

- `src/brief_crew/builder/runtime.py:126-156, 406-439, 414, 441-468, 476-488, 612-667, 914-952`
- `src/brief_crew/service/{builder_runner.py:9-34, 92-136, 177-206, builder_rehydrate.py:95-199, registry.py:909, 1206, 1266-1335, 1496, 1612, 1766, 1830, 2403-2438, 2567-2592, models.py:125, 162, 398, app.py:756-776, 1061-1096, 1148, persistence.py:71-86, 101-110, 185-200, 533-549, 623, runner.py:28-41, 65}`
- `src/brief_crew/events/{serializer.py:472, 478, models.py:20}`; `src/brief_crew/config.py:197-219, 707-712, 821-829, 1078, 1895`
- `crewai/events/types/llm_events.py:90, 136`; `crewai/tools/tool_failure.py:57-69`; `crewai/crew.py:729`; `crewai/llm.py:372-388`; `docs/crewai-notes.md` §1, §4, §8, §9
- `docs/chatdev-notes.md` §3 (the reference's regex handshake); CLAUDE.md §8, §9, closed items 19, 32, 35; remaining-work item 41
- Gauntlet: "Error handling", "Flow testing", rubric 11–14

## Status

**Built · 2026-09-04.** All twelve criteria met. A published graph was already
runnable; it is now inspectable, testable and recoverable — it says what the
agent said, which edge it took and what the plan is; it retries what is worth
retrying and only that; it routes a failure instead of dying of one; and it can
be started again from the node that failed rather than from node 1.

| # | Criterion | State | Shown by |
| ---: | --- | --- | --- |
| 1 | `AuthoredAgentTests`: the synthetic factory gets the whole block; a real `Agent` has `llm.model`, `max_tokens`, `temperature`, `stream` | **met** | `test_builder_runner.py::AuthoredAgentTests` (8) |
| 2 | `max_tokens == GRAPH_BUDGET_CALL_COMPLETION_TOKENS`; cost per registry model, `None` for an unknown one | **met** | `test_run_result_and_cost.py::AuthoredCompletionBoundTests` (3) |
| 3 | `resolve_credential` under `current_run_user`; `credential-not-yours`; a sentinel in no frame, state, row or export | **met** | `test_credentials_runtime.py` (16) |
| 4 | retry ×3, the third on the fallback; `max_retries: 0` fails first; cancel between attempts | **met** | `test_retry.py` (13) |
| 5 | `on_error: route` reaches `completed` with `err__<node>`; `fail` reaches `failed` | **met** | `test_error_routing.py` (5) |
| 6 | `resume_from` replays `a`, `b`, runs `c`, equals a clean run; 404; `replay-missing-output` | **met** | `test_replay.py` (10) |
| 7 | `dry_run` 200 and nothing created; `test` writes `mode`; `node_test` 422; `/state?step=` | **met** | `test_run_modes.py` (16) |
| 8 | `utterance` truncated at 4,096; ≤ 4 chunk frames/s/call; `edge_traversal` before `NODE_START`; `stage` = layer count | **met** | `test_utterance_frames.py` (21) |
| 9 | `runs.mode` on a shipped table; a pre-existing row reads NULL → `run` | **met** | `test_additive_migration.py` (26, 2 new) |
| 10 | a v1 row through the upgrade; a v2 row naming a retired model skipped with `model-unknown`, and the process boots | **met, with one stated limit** | `test_builder_rehydration.py::SchemaAndModelDriftTests` (3) |
| 11 | `test_restart_recovery.py` still passes; a `test`-mode run interrupted mid-method is failed at startup | **met** | `test_restart_recovery.py` (25, 3 new) |
| 12 | `e2e/visual/run-canvas.spec.ts` still passes | **met** | 3 passed against `SYNTHETIC=1` on 8101 |

### Measured, 2026-09-04, in this worktree

```text
Python          2243 run · 0 failures · 6 skipped · 109.5 s   (this plan's baseline 2119)
Frontend unit   1468 passed in 74 files                        (baseline 1426 in 73)
vue-tsc -b --force   exit 0
npm run build        green
E2E             73 passed, 2 failed - both in `e2e/visual/builder-canvas.spec.ts`
                and neither this plan's; see "Not ours" below
```

Part of both suite deltas is another agent's uncommitted template work in this
shared worktree (`tests/builder/test_templates.py`, `frontend/tests/templates.spec.ts`),
not this plan's. **This plan spent $0.00**: every billable node in every test is
built by the double `SYNTHETIC=1` installs, and the two tests that need a REAL
`Agent` construct one, which calls no model.

### Two things measured that no plan knew

**1. CrewAI persists NOTHING for an ordinary declarative run.** A two-node graph
published, launched and completed on the service persistence leaves
`flow_states` EMPTY; the only writer is `save_pending_feedback`, on the pause a
gate raises. So D5's premise — "the source run's last `flow_states` row" — held
only for a run that had paused, `GET /state?step=` answered `{}` for every step,
and `resume_from` had nothing to replay from. Both are this plan's, so the write
is: `builder_state_sink` checkpoints one row PER NODE from `_record`. Per node
and not per run, because `?step=` is a question about a MOMENT and a single
end-of-run row would answer every step with the final state and look exactly as
if it worked. `test_credentials_runtime.py` asserts the rows exist before
asserting the sentinel is not in them, so that leg cannot go vacuous either.

**2. An authored node could route past the §6a price ceiling.** The ceiling is
enforced by `provider.max_price` on the escalation preset; an authored node
builds its own `LLM` from the author's own registry model and carried no
`provider` block at all. `openrouter_authored_params` now assembles one —
`max_price` and, when the author set one, the reasoning effort — in ONE
`provider` object, because JSON has no merge and a second writer of that key
wins silently. Deliberately no `sort`: the author chose the model, so this
module does not also choose the endpoint.

### Four departures, each where the plan and the code disagreed

Stated rather than smoothed over.

1. **`err__<node>` stays a STRING, not D4's `{error_class, message}` mapping.**
   `runtime.py`'s own docstring records that a flat `${state.x}` is the only
   reference shape ever measured resolving — nested access into a sub-dict was
   not — so a mapping here would be a value the error port's successor cannot
   read, which is the one thing the key exists for. The string is
   `ClassName: sentence`, and the machine-readable `error_class` is on the
   `node_error` frame. It also keeps plan 09's `ErrorRouterTests` green rather
   than rewriting an assertion that was right.
2. **Criterion 4's "`node_error ×3` … and the run completes" is tested BOTH
   ways**, because the two clauses cannot both hold of one run under
   `on_error: fail`: three failed attempts and a completed run only coexist when
   the node is routed. So the criterion's own numbers are asserted on a
   `route` node whose three attempts all fail, and a second test asserts the
   other reading — the fallback attempt SUCCEEDS, two `node_error`s, run
   completes normally.
3. **`dry_run` is answered BEFORE the rate limiter**, which is the one place
   this endpoint's ordering bends. Criterion 7 asks for it and the reason holds:
   a preview the canvas fires on every edit must not compete with Launch for a
   launch allowance. The residual is an unthrottled existence oracle for a
   workflow id, and it is not a NEW one — `workflow_visible_to` answers the same
   404 that `GET /api/builder/workflows/{id}` already answers unthrottled.
4. **Criterion 10's "a v1 row rehydrates through the upgrade" is asserted as the
   SEAM being in the read path, not as a live v1 → v2 walk.** The mapping is
   registered and inert at head: `config.BUILDER_DOCUMENT_SCHEMA` is still
   `builder.flow/v1`, and moving it is a two-suite contract change plan 15's own
   module docstring describes and does not take. `tests/builder/test_upgrade.py`
   proves the walk under a patched constant. Asserting more here would be
   asserting a constant nobody has moved.

### Four deliberate breaks, and what each looked like

Each was applied, watched go red, and reverted.

| broken | red |
| --- | --- |
| the 250 ms window in `_coalesce_chunk` | `AssertionError: 40 != 1`, and `500 not less than or equal to 4` |
| `max_tokens` default and `stream=True` | `AssertionError: None != 4253` ×2, `False is not True` |
| `_state_sink` returning `None` | `'out__scoper' not found in {}`, and the anti-vacuity guard: `[] is not true : the run wrote no state at all; this would be vacuous` |
| `NodeRegistry.edges` built from the wrong field | `('a', 'b') not found in frozenset({('b', 'b'), ('a', 'a'), ('idea', 'idea')})` |

A fifth lives in the suite permanently:
`test_retry.py::test_a_deliberate_break_of_the_closed_list_would_be_visible`
patches `_is_retryable` to say yes to everything and asserts the refusal is then
tried three times, which is what makes the closed list a mechanism rather than a
comment.

### Not ours

`e2e/visual/builder-canvas.spec.ts` fails two snapshots — `problem state — dark`
and `problem state — light`. This plan touched **one** file under `frontend/`
(`tests/builderApi.spec.ts`, to enumerate the new `compiled` route) and no
frontend source at all. The failing capture presses `2` to add a node, whose
card renders a default model out of `frontend/src/data/models.ts` — one of the
files another agent has uncommitted in this worktree, along with
`types/builder.ts` and `TemplateGallery.vue`. Their snapshots need regenerating
with their change.

### For the Integrator

- **C6 and C7 are landed as written**, with the four departures above. No new
  `FrameKind` member: all five names are `details.stage` discriminators.
- **`NodeRegistry` gained one field, `edges`** — every `(from, to)` pair the
  author drew. It is what stops `edge_traversal` inventing an edge on two
  interleaving branches; an empty set (both hand-written flows) falls back to
  execution order. Additive, defaulted, and `from_flow_structure` is untouched.
- **`RunExecution` gained `mode` and `derived`**, both defaulted, both ignored by
  the four runners that do not read them.
- **`config.py` gained five names**: `MAX_UTTERANCE_CHARS`,
  `MAX_FRAME_PREVIEW_CHARS`, `MAX_NODE_ERROR_CHARS`,
  `STREAM_CHUNK_COALESCE_MS`, and `openrouter_authored_params`.
- **`SECRET_KEYS` gained `env`** (D2's fourth name). It ends in none of the
  suffixes, so only an exact entry catches it.
- **The rehydration skip reason now carries the problem CODES** beside the
  compiler's sentence. `model-unknown` in a log line is the difference between
  "some graph broke" and "these three name a model we withdrew".
- **`BuilderTestInputStore` is a READ-ONLY loader in `builder/store.py`.** Plan
  13 owns that table and will bring the CRUD; this is the one query C7's
  `test_input_id` implies, put where the SQL for every other builder table
  already lives.
- **`SYNTHETIC_FAILURE`** is a new environment knob on the free factories
  (`[node:]reason[:times]`, `reason` in `rate_limit` / `refusal`). Nothing reads
  it in production; it is what makes the retry loop and the error port testable
  without money, and it is read PER INSTANCE so a test needs no restart.
- **Item 3's fifth compare-and-set path is untouched** and this plan adds no
  sixth.

Open questions for the owner:

- **`stream=True` on every authored `LLM` and `Crew` has never met a paid run.**
  D7 asks for it and the tests prove the flags are set, but what a streaming
  completion does to an authored task carrying `output_pydantic` is a question
  only a real call answers. It is the single highest-value thing to watch on the
  first paid run of a user-authored graph (remaining-work item 40).
- **`GET /api/runs/{id}/state` has no client**, by design — plan 11 owns the
  console. Same for `GET /api/builder/workflows/{id}/compiled`, whose panel is
  11's; `frontend/tests/builderApi.spec.ts` accounts for the route in the
  meantime so it cannot sit declared and unknown to the client.
