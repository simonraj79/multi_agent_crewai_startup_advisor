# `builder-agentfail-2` — re-proof of B3 / D1 at `c608953`, PAID ($0.00)

Run **2026-09-06** by V-PROOF, second pass, against **`c608953`**. Same backend
and rules as `../validator-live-2`; the published graph `ug_fd12e0a6` was
re-launched unchanged (boot log: `rehydrated 2 published builder graph(s):
ug_fd12e0a6, ug_4e7e952f`).

| | |
| --- | --- |
| app run id | `45cc3736-ed0b-466a-9dc6-e7f69ff0eea0` |
| Langfuse trace id | `45cc3736ed0b466a9dc6e7f69ff0eea0` |
| trace URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/45cc3736ed0b466a9dc6e7f69ff0eea0` |
| workflow / gates / env | `ug_fd12e0a6` / `auto` / `live`, user `proof-runner` |
| terminal | `failed`, 0.93 s |
| frames | 50 |
| observations | 32 — SPAN 6, EVENT 19, AGENT 1, GENERATION 6 (all ERROR) |
| app usage / OpenRouter billed | 0 calls, 0 tokens, **$0.00** / no generation record |
| exporter | `frames_enqueued=50 frames_dropped=0 observations_sent=35 http_errors=0 lookup_ok=0 lookup_failed=0` |

## FIXED: `run_metrics` now has a fallback and says where it came from

```json
"run_metrics": {"source": "exporter-tally", "reason": "failed",
                "usage": {"call_count": 6, "prompt_tokens": 0,
                          "completion_tokens": 0, "total_tokens": 0,
                          "cost_usd": null}}
```

Pass 1's `builder-agentfail` had `run_metrics: null`, because this run emits no
`METRICS_UPDATED` frame at all. It now reports the exporter's own tally and
labels it `source: "exporter-tally"`, so a reader can tell a tally from a
snapshot. (`../validator-live-2` and `../builder-toolfail-2` both read
`source: "app-snapshot"`, which is the other half of the same change working.)

## FIXED: the D3 instrument

`open-spans.txt` now reads

```text
unfinished spans (non-EVENT observations with endTime null): 0
observations examined: 32
  observations with endTime null, ALL types  : 19
  of those, EVENT (no endTime by construction): 19
  of those, able to end and still open (D3)   : 0
```

— the split pass 1 had to compute by hand is now the instrument's own output.

## NOT FIXED: no observation names the exception class

This is the row the re-proof was for, and it still fails. Measured over
`langfuse-observations.json`:

| observation | `metadata.error_class` | `statusMessage` begins |
| --- | --- | --- |
| AGENT `Channel Sounder` `31c5efabeebacd88` | **None** | `Error code: 400 - {'error': …` |
| task SPAN `15b7f9b00eb6da1b` | **None** | `Error code: 400 - {'error': …` |
| node SPAN `584080214b55ad3b` | **None** | `Error code: 400 - {'error': …` |
| run SPAN `067a1fdeec67af39` | **None** | `Error code: 400 - {'error': …` |
| `trace.output.error_class` | **null** — the KEY is new at `c608953`, the value is not set | |

Not one observation in the trace carries a non-null `error_class`.

### Why, measured — the class is on a frame that closes nothing

`_error_fields` (`langfuse_exporter.py:1475`) reads `details["error_class"]` and
`details["error"]` from **the frame that closes the span**. In this run:

```text
frames carrying error_class: [(47, 'NODE_END', 'BadRequestError')]   <- exactly one
```

and every span closes on a different frame:

| observation | endTime | frames at that timestamp |
| --- | --- | --- |
| agent, task | `17:25:33.983Z` | seq **45** `AGENT_CALL` — has `error`, **no** `error_class` |
| node | `17:25:33.986Z` | seq **47** (`error_class`, text under `message`) and seq **48** (`error`, no class) |
| run | `17:25:33.989Z` | seq **49** `WORKFLOW_END` — has `error`, **no** `error_class` |

The node is the only ambiguous one, and it is settled by the text: its
`statusMessage` is **byte-equal to seq 48's `error`** and **not** equal to seq
47's `message`. So seq 47 — the one frame that has the class — closed nothing;
it became an EVENT.

Two independent causes, both visible in that table:

1. **The app emits two `NODE_END` frames.** The first carries `error_class`,
   `attempt`, `will_retry`, `routed`, `fallback_model` and its text under
   **`message`**; the second carries the text under `error` and no class.
   `_error_fields` reads `error`, so even if it *did* close the span the first
   frame would produce the fallback string, not the message.
2. **The agent, task and run spans are closed by frames that never carry a class
   at all** — `AGENT_CALL` (seq 44-46) and `WORKFLOW_END` (seq 49-50). The
   commit's premise, "the NODE_END frame's error_class now reaches the agent and
   task spans it closes", does not hold: NODE_END closes neither of them here.

The information exists (`app-frames.ndjson` seq 47) and reaches no observation.
`../builder-toolfail-2` reproduces the same shape with
`ToolExecutionFailedError`, so it is not specific to this failure class.

## Screenshot

`B3-failure.png` — AGENT `Channel Sounder` `31c5efabeebacd88` open at
`…?observation=31c5efabeebacd88`. It shows the ERROR badge, `task_attempts: 6.00`
on the parent task, the six ERROR generations, and an Error panel carrying the
provider's 400 message **with no class prefix**; the Metadata list below it has
`observation_role`, `null_fields`, `frame_ts`, `event_type`, `frame_kind`,
`frame_seq`, `task_name` — and **no `error_class` row**. It is a picture of the
gap, not of the fix.
