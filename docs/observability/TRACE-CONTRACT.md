# Trace contract — what the app writes to Langfuse, and where

Written 2026-09-05 by the orchestrator. Both builders (exporter and tooling)
code against THIS file; a reader of Langfuse who has this page can find every
value the Definition of Done asks for. Nothing here names a flow, an agent, a
task or a tool of this repository: every identity value is copied off the
CrewAI event that carried it.

## 1. Ids and grouping

| Langfuse field | Value | Why |
| --- | --- | --- |
| trace `id` | deterministic from the app `run_id` (Langfuse's seeded trace-id derivation, 32 hex) | idempotent re-emission; a reader can compute it |
| trace `sessionId` | the app `run_id`, verbatim | the console URL carries the run id; no lookup table |
| trace `name` | the app `workflow_id` (e.g. the flow's registered id, or the builder document id) | which flow ran |
| trace `userId` | the run owner's user id, else `anonymous` | who launched it |
| `environment` | `synthetic` when the run used the no-cost doubles, else `live` | a synthetic run's usage is fabricated and must not pollute cost views |
| trace `tags` | `[workflow_id, "gates:" + gates_mode, "mode:" + run mode]` - the workflow id the registry knows the flow as, the gate mode, and the run mode (`run`, or `resume` for a run adopted after a restart) | filterable without opening the trace |
| trace `metadata` | `run_id`, `workflow_id`, `app_session_id`, `gates`, `synthetic` (bool), `user_id`, `graph_version` (if known), `run_metrics` = the LAST metrics snapshot the run emitted (a `run_completed` snapshot arrives AFTER the terminal frame and must still be applied), `computed_result` = the run's deterministic result summary when the flow emitted a VERDICT-kind frame (policy-filtered: numbers and enums, never free text), and `unhandled_event_counts` = the serializer's per-class tally of CrewAI events it deliberately did not turn into frames (C3) | A3, and the run total is readable without summing generations |
| trace `input` | under default policy: `{"input_keys": [...], "input_chars": n, "input_fingerprint": sha256}`; with capture on: the redacted inputs | user-entered text is content |
| trace `output` | `{"status": terminal status, "reason": redacted one-liner or null}` | the run's end is legible from the trace list |

The `run` SPAN is the root: it has NO parent observation, and every other
observation descends from it. Observation ids are deterministic from `(run_id,
frame identity)` so that a re-delivered frame updates rather than duplicates. Start and end times come from
the **frame timestamps**, never from the exporter's clock — the exporter runs
behind a queue.

## 2. Observation hierarchy

```text
trace (one per run; sessionId = run_id)
└── SPAN  run                     name: "run"                   the whole run; ends with the terminal frame
    └── SPAN  node                name: node label or id        one per flow-method (node) start/end frame
        └── SPAN  task            name: task name (see §3a)     when the frames carry a task boundary
            └── AGENT agent       name: agent role              one per agent execution start/end (Langfuse's native AGENT type; metadata.observation_role = "agent")
                ├── GENERATION    name: model                   one per LLM call (before/after or failed)
                ├── TOOL          name: tool name               one per tool call (started/finished/error)
                └── EVENT         name: event kind              anything else the frames carry
    └── EVENT  gate               name: "gate:" + gate id       open / answered / expired
```

If a frame arrives without a task boundary, the agent span hangs directly off the
node span; if without an agent, the observation hangs off the node span. If the
Langfuse ingestion in use has no TOOL type, a SPAN with `metadata.observation_role
= "tool"` is used and the tooling treats it as TOOL.

An unknown frame kind or event type becomes an EVENT observation named after the
frame's `event_type`, carrying the frame's redacted `details` as metadata. It is
never dropped silently (C3).

### 3a. A task name is sent only when it is DECLARED (amended 2026-09-23)

CrewAI sets a task event's `task_name` to `task.name or task.description`, so a task
with no `name` - every builder task - reports its **rendered description**, with the
user's input interpolated. Found on production during the routing live run: the
customer's message was reaching the task span's name, `metadata.task_name`, an
EVENT's details and an error's status message, with content capture OFF.

So `task_name` travels only if `config.declared_task_name()` accepts it (identifier
shaped: `[A-Za-z_][A-Za-z0-9_.-]{0,63}`, no spaces). Otherwise `metadata.task_name`
is null, the task span is named after its node span, an EVENT carries the name's
length and hash instead, and a failure reads "the task failed". Ids and the
run -> node -> task -> agent hierarchy do not change. A hand-written task named with
spaces would lose its name here; the repository's crews all use identifier names.
`tests/observability/test_task_name_is_not_content.py` holds it.

## 3. Attributes on EVERY observation (`metadata`)

`run_id`, `node_id`, `agent_role` (or null), `task_name` (or null),
`frame_seq` (the sequence number of the frame that OPENED the observation - for
a TOOL that is the `before` frame, never the `after`), `frame_ts` (that frame's
timestamp), `frame_kind`, `event_type`. All seven keys are present on every
observation, the `run` span and edge-entered node spans included; a value the
frame does not carry is `null`, never an absent key.

## 4. GENERATION specifics

| Field | Value |
| --- | --- |
| `model` | the model string off the LLM event, provider prefix as the app sees it |
| `usageDetails` | `input`, `output`, `total` tokens as the frame carries them; `cached`/`reasoning` when present |
| `costDetails.total` | the app's estimate from `compute_cost_usd` at emission time |
| `metadata.cost_source` | `app-estimate` at emission; `openrouter-billed` after the out-of-band resolution below succeeds |
| `metadata.response_id` | OpenRouter's generation id (`gen-…`) from the frame |
| `metadata.openrouter_cost_usd` | set only by the resolution below |
| `metadata.prompt_fingerprint` | sha256 over the rendered messages (role + content, in order), computed by the FRAME SERIALIZER on the LLM `before` frame (`events/serializer.py`) from `LLMCallStartedEvent.messages`; the exporter copies it. The content itself never enters a frame. `metadata.prompt_fingerprint_basis` names what was hashed (`messages`), or, when the event carried no messages, `node|agent_role|task_name|model` |
| `metadata.message_count`, `metadata.prompt_chars`, `metadata.completion_chars` | always; the first two from the same `before` frame, `completion_chars` from the utterance frame (true length, before the frame's own truncation) |
| `input` / `output` | `input` is ABSENT under EVERY policy: prompt content never enters the frame pipeline (the app's own run store would otherwise persist every prompt, a wider disclosure than Langfuse), so a generation is identified by `prompt_fingerprint` + `message_count` + `prompt_chars`. `output` is ABSENT under the default policy and is the redacted utterance text when `LANGFUSE_CAPTURE_CONTENT=1` |
| `level` / `statusMessage` / `metadata.error_class` on ANY error observation (generation, tool, agent, task, node, run) | `ERROR`; `statusMessage` = `ExceptionClass: redacted message` when the frame carries an error class (the NODE_END / AGENT / LLM error frames carry `error_class`), else the redacted message alone; `metadata.error_class` = the class name or null |
| `metadata.finish_reason` | when the frame carries it |
| `metadata.attempt` | 1-based index of this generation within its task (retries are legible as attempt 2, 3 …) |

**Billed-cost resolution.** When `LANGFUSE_RESOLVE_BILLED_COST` is on, the
exporter thread resolves each `response_id` against OpenRouter
`GET /api/v1/generation?id=` after the generation has been sent. OpenRouter
indexes a generation tens of seconds after it completes (measured 404 for
60 s+ on the proof runs), so the resolution is a DEFERRED, RETRIED lookup on
the export thread - bounded by a per-run count, a per-request timeout and a
total attempt window - and it UPDATES the observation's
`costDetails.total`, `metadata.openrouter_cost_usd`, `metadata.cost_source`, and
`metadata.provider` (the serving provider). A failed lookup leaves the estimate
and says so in `metadata.cost_source = "app-estimate (lookup failed)"`.

## 5. TOOL specifics

`name` = tool name; `input` = redacted arguments under capture, else
`{"arg_keys": [...], "arg_chars": n}`; `output` = same policy on the result;
`metadata.tool_status`, `metadata.result_count`, `metadata.query` only when the
frame already carries them (the frame pipeline already bounds and redacts these);
`level = ERROR` and `statusMessage` on a tool error.

## 6. Terminal handling

| App terminal frame | Trace `output.status` | `run` span | Open observations |
| --- | --- | --- | --- |
| completed | `completed` | ended at frame ts, level DEFAULT | none expected; any still open are ended at the same ts with level WARNING and `statusMessage: "ended by run completion"` |
| failed (flow error / runner error) | `failed` | ended, level ERROR, statusMessage = error class + redacted message | ended at the same ts, level ERROR |
| cancelled | `cancelled` | ended, level WARNING, statusMessage = "cancelled by operator" | ended at the same ts, level WARNING, statusMessage "cancelled" |
| budget-stopped (`MAX_RUN_COST_USD`) | `failed` | ended, level ERROR, statusMessage names the ceiling and the figure | as failed |

Nothing is ever left without an end time once a terminal frame has been seen
(D3). A run that pauses at a human gate is NOT terminal: its spans stay open and
a `gate` EVENT records the pause; resume continues in the same trace.

## 7. Scores (generic only — C1)

Every score name here is a fact about a run, a task or a check. None names an
agent, a task, a tool, a crew, a flow or a workflow of this repository, which
is what keeps `tests/observability/test_no_flow_identifiers.py` green over the
modules that write them.

| Score name | Attached to | Type | `score_id` | When it is written |
| --- | --- | --- | --- | --- |
| `guardrail_passed` | the task SPAN, falling back outwards to the agent span, then the node span, then the trace | numeric 0/1 | minted by Langfuse | per guardrail result frame, `stage == "after"` |
| `task_attempts` | the task SPAN | numeric | minted by Langfuse | when the task span closes; the number of generations under that task |
| `gate_outcome` | the task SPAN of the gate's node, falling back outwards the same way | **categorical** | minted by Langfuse | on a `GATE_CLOSED` frame carrying a non-empty `outcome`; the value is that outcome string (`approve` / `revise`), bounded to 64 characters |
| `run_succeeded` | the trace | numeric 0/1 | minted by Langfuse | at the terminal frame; `1` when the status is `completed` |
| `run_status` | the trace | categorical | minted by Langfuse | at the terminal frame; the terminal status string |
| `human_rating` | the **trace** | **categorical** | `f"{trace_id}-human_rating"`, deterministic | whenever a person rates or re-rates the run through `PUT /api/runs/{id}/rating` or the admin door. See below |

**Corrected 2026-09-18.** The `guardrail_passed` row said "falls back to the
agent span, then the trace" and omitted the node span; the code is
`scope.task or scope.agent or scope.span` and then the trace
(`langfuse_exporter._handle_score`). The four scores this table already listed
are otherwise exactly what the exporter writes, checked against every
`self._call(state, "score", …)` site.

### `human_rating` is the one score that is not driven by a frame

It arrives **after the trace closed**, sometimes days later, from a person
clicking a button on a finished run. There is no frame to attach it to, so it
is addressed by trace id: `observability/scores.py` imports `trace_id_for`
from `backend.py` rather than re-deriving it, because a second derivation is a
second answer to "which trace is this run".

Four rules, all of them measured against Langfuse cloud on SDK 4.15.1 rather
than reasoned:

* **One deterministic id, and every write is an upsert.** `create_score` with
  no id APPENDS, so without one a re-rating leaves two scores on the trace and
  a clear leaves both while the app's own row says unrated.
* **Always CATEGORICAL, with the word as the value.** Under one id, NUMERIC to
  CATEGORICAL is accepted and CATEGORICAL to NUMERIC is silently ignored, so a
  design that changes a score's type on a value change fails in one direction
  without an error.
* **A write never deletes.** `create_score` is queued asynchronously by the
  SDK and `delete_score` is a synchronous HTTP call, so a delete issued beside
  a create overtakes it, 404s, and lets the create land and stay. Measured:
  four ratings in eight seconds left a stale score permanently.
* **A clear is the only delete, and it is issued twice.** Once immediately and
  once after `config.RATING_SCORE_CLEAR_SWEEP_SECONDS` (45 s), the second pass
  re-reading the database first so a person who re-rates inside the window
  keeps their rating. Ingestion lag on the upsert path was measured above 12 s
  and under roughly 20 s. The delete is the **legacy** `score_v1` route
  (`client.api.legacy.score_v1.delete`), because the v2 score API has none.

`comment` carries the rater's note and is written **only** under
`LANGFUSE_CAPTURE_CONTENT` (§8), decided in `observability/scores.py` and not
at the transport. The full description, including the routes and what is not
built, is [`RUN-LABELS.md`](RUN-LABELS.md).

## 8. Content policy (E3)

Default: no message content, no completion text, no tool argument or result
text, no user-entered input text leaves the process. What leaves instead:
fingerprints, counts and character lengths as above.

`LANGFUSE_CAPTURE_CONTENT=1`: content is sent after passing (a) the existing
`events/redaction.py` rules and (b) a key-shape scrubber for at least the
prefixes `sk-or-`, `sk-lf-`, `pk-lf-`, `fc-`, `ghp_`, `github_pat_`, `pcsk_`,
`AIza`, and any value currently held in the process's own credential
environment variables (compared, never logged). Strings are bounded to the same
ceilings the frame serializer uses.

## 9. Knobs (all in `config.py`, all read from the environment)

| Knob | Default | Meaning |
| --- | --- | --- |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | unset | credentials; when either key is absent the exporter is a no-op that logs one line at startup |
| `LANGFUSE_EXPORT_ENABLED` | `1` when both keys are present, else `0` | master switch |
| `LANGFUSE_CAPTURE_CONTENT` | `0` | §8 |
| `LANGFUSE_ENVIRONMENT` | derived (`synthetic` / `live`) | override |
| `LANGFUSE_RESOLVE_BILLED_COST` | `1` | §4 |
| `LANGFUSE_QUEUE_CAPACITY` | bounded, same order as the frame writer's | drop-oldest with a counter |
| `LANGFUSE_FLUSH_INTERVAL_SECONDS` | 0.25 | drain cadence; it is also the span-start error bound the DoD B4 revision names (the SDK cannot set a start time), which is why it is small rather than a throughput tuning |
| `LANGFUSE_HTTP_TIMEOUT_SECONDS` | small (≤ 5) | never let a slow host hold the thread |

## 10. Exporter self-report

The exporter keeps per-run counters — `enqueued`, `dropped`, `sent`,
`http_errors`, `lookup_ok`, `lookup_failed`, `enqueue_latency_us` p50/p95 — and
logs ONE summary line per run when the trace closes. Any exporter failure is
logged at most once per run. The run's own status, result and frame counts are
unaffected by anything in this file (E2).

---

## Amendment A1 — §3's null, and the transport that cannot carry one

Added 2026-09-06 by B-EXP, under the rule that a builder may append here only
when the contract is impossible to meet as written. **§3's sentence "a value
the frame does not carry is `null`, never an absent key" cannot be satisfied by
the Langfuse 4.15.1 OTel path**, and the reason is one line of the SDK rather
than a choice this exporter makes:
`langfuse/_client/attributes.py::_flatten_and_serialize_metadata` maps a `None`
metadata value to a `None` OpenTelemetry attribute value (`_serialize(None)` IS
`None`), and OpenTelemetry drops an attribute whose value is `None` rather than
sending a JSON null. Measured against the live API: 11 of 33 observations came
back with `agent_role` and `task_name` **absent** after the exporter set both
to `None`. Sending the string `"null"` instead would be worse — it is a value,
and nothing downstream could tell it from an agent actually called that.

**What the exporter does instead, and it preserves what §3 was protecting.**
Every observation additionally carries

| key | value |
| --- | --- |
| `null_fields` | a comma-separated list of the §3 keys this frame did not carry; **always present**, and the empty string when none are null |

so the distinction §3 exists for survives: a §3 key that is absent **and named
in `null_fields`** means the frame carried none; a §3 key that is absent and
**not** named there means something is wrong. Only `agent_role` and `task_name`
are nullable — `run_id`, `node_id`, `frame_seq`, `frame_ts`, `frame_kind` and
`event_type` are on every frame by construction.

Tooling that checks §3 completeness should read `null_fields` rather than
expecting a null. `tests/observability/test_trace_shape.py` pins both halves.
