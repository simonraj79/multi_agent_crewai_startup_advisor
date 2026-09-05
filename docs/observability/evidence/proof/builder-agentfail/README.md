# `builder-agentfail` — a builder-authored graph whose agent's LLM call is refused, PAID ($0.00)

Run 2026-09-05 by V-PROOF. Code at `e68dac4`. Same paid backend, same
signed-in user `proof-runner`. Launched **after** the concurrent pair, as the
plan directs.

| | |
| --- | --- |
| app run id | `ca13fc73-0ca9-4a31-bc8c-6e53ed1d562d` |
| Langfuse trace id | `ca13fc730ca94a31bc8c6e53ed1d562d` |
| Langfuse session URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/ca13fc73-0ca9-4a31-bc8c-6e53ed1d562d |
| Langfuse trace URL | https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/ca13fc730ca94a31bc8c6e53ed1d562d |
| workflow / gates / env | `ug_fd12e0a6` (graph_version `4a1ba2a50916d665`) / `auto` / `live` |
| terminal status | `failed`, 0.75 s |
| frames | 50 |
| observations | 32 — SPAN 6, EVENT 19, AGENT 1, GENERATION 6 |
| scores | 3 (`run_succeeded` 0, `run_status` `failed`, `task_attempts` **6**) |
| app usage | **0** calls, 0 tokens, **$0.00** |
| OpenRouter billed | **no generation record exists** — the absence is the evidence |

The document was validated (`validate.json`: `valid: true`, `problems: []`,
`identity_checked: true`, static estimate $0.022465), created
(`create-workflow.json`, id `ug_fd12e0a6`) and published
(`publish.json`, `gated_before_spend: true`) in this session.

## The injection, and what OpenRouter said

`llm.max_tokens: 2000000000` on a real roster model
(`google/gemini-3.5-flash-lite`). The provider answered, verbatim, on the
trace and in `app-run.json.error`:

> Error code: 400 - {'error': {'message': "This endpoint's maximum context
> length is 1048576 tokens. However, you requested about 2000000311 tokens
> (311 of text input, 2000000000 in the output). Please reduce the length of
> either one, or use the context-compression plugin to compress your prompt
> automatically.", 'code': 400, 'metadata': {'provider_name': None}}}

That message names the endpoint's own context length, so the request reached
OpenRouter's router and was refused there rather than locally.

**Six** generations, not one: CrewAI made three agent attempts and two LLM
calls per attempt (six distinct `call_id`s in `app-frames.ndjson`, seq
20/23/29/32/38/41, each with a paired `stage: "error"` frame). Every one is a
GENERATION at `level = ERROR` in Langfuse, so the six are legible as six.
`usage.call_count` is **0** because no call *completed*, and no token frame was
emitted — the absence `inject.md` §5.3 asked to be asserted rather than assumed.

## Screenshots and the observation ids each shows

| file | URL | shows |
| --- | --- | --- |
| `B3-failure.png` | `?observation=4d48441dc522611c` | the failing AGENT **`Channel Sounder`** `4d48441dc522611c` at ERROR with the provider's message as its `statusMessage`; its parent task SPAN `1b64cf88d2b52be2` at ERROR carrying `task_attempts: 6.00`; the six GENERATIONs at ERROR beneath it; metadata `observation_role: "agent"`, `event_type: "MODEL_CALL"`, `frame_kind: "llm"`, `frame_seq: 20`, `task_name` |
| `B3-run-span-failed.png` | `?observation=7b7b091f59ba3cd2` | the **run-level** observation `7b7b091f59ba3cd2` at ERROR — the trace ends with `output.status = "failed"` and the reason, it does not merely stop |

Failing GENERATION ids: `c9ccc2da79d92401`, `173ca4a2d24c9222`,
`63a291dbd9758626`, `5cc6b566e7874812`, `fba97a13179c570b`,
`fa782d39b6ef9b77`. Node SPAN `sound_the_channel` `56422a601804505e`.

## The one thing B3 asks for that is NOT there

**No exception class is named.** The `statusMessage` on the agent, task, node
and run observations is the provider message alone; `metadata.error_class` is
absent on all four. The class **is** in the app's own frame
(`NODE_END` seq 47 carries `error_class: "BadRequestError"`; the toolfail run's
carries `"ToolExecutionFailedError"`), so this is a mapping gap in the
exporter, not information the app never had. `TRACE-CONTRACT.md` §6 asks for
"error class + redacted message". Only the TOOL observation satisfies it, and
only because the frame's own text is already a repr.

## `run_metrics` is null on this trace

`trace.metadata.run_metrics` is `null` here and a full `run_completed`/
`run_failed` snapshot on the other three paid runs. Cause: this run emitted
**no** `METRICS_UPDATED` frame at all (`app-frames.ndjson` has none), because
nothing billable ever completed. Faithful to the frames; worth knowing before
reading a trace's metadata as a cost source.
