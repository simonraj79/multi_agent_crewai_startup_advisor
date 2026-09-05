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
        └── SPAN  task            name: task name               when the frames carry a task boundary
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
| `input` / `output` | ABSENT under the default policy; present, redacted, when `LANGFUSE_CAPTURE_CONTENT=1` |
| `level` / `statusMessage` | `ERROR` + `ExceptionClass: redacted message` on a failed call; `DEFAULT` otherwise |
| `metadata.finish_reason` | when the frame carries it |
| `metadata.attempt` | 1-based index of this generation within its task (retries are legible as attempt 2, 3 …) |

**Billed-cost resolution.** When `LANGFUSE_RESOLVE_BILLED_COST` is on, the
exporter thread resolves each `response_id` against OpenRouter
`GET /api/v1/generation?id=` after the generation has been sent, bounded by a
per-run count and a per-request timeout, and UPDATES the observation's
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

| Score name | Attached to | Type | Value |
| --- | --- | --- | --- |
| `guardrail_passed` | the task SPAN (falls back to the agent span, then the trace) | numeric 0/1 | per guardrail result frame |
| `task_attempts` | the task SPAN | numeric | number of generations under that task |
| `run_succeeded` | the trace | numeric 0/1 | terminal status == completed |
| `run_status` | the trace | categorical | the terminal status string |

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
| `LANGFUSE_FLUSH_INTERVAL_SECONDS` | ≈ 1.0 | batch cadence |
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
