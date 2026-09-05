# `builder-agentfail-3` — B3 / D1 MET at `58a1c0b`, PAID ($0.00)

Run **2026-09-06** by V-PROOF, third pass, against **`58a1c0b`**. Same backend and
rules as `../validator-live-3`; the published graph `ug_fd12e0a6` was re-launched
unchanged, **after** the concurrent pair had settled, as the plan directs.

| | |
| --- | --- |
| app run id | `f371b3b9-6ca5-4b8b-9f63-9c34249ef440` |
| Langfuse trace id | `f371b3b96ca54b8b9f639c34249ef440` |
| trace URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/f371b3b96ca54b8b9f639c34249ef440` |
| workflow / gates / env / user | `ug_fd12e0a6` / `auto` / `live` / `proof-runner` |
| terminal | `failed`, 0.65 s |
| frames | 50 |
| observations | 32 — SPAN 6, EVENT 19, AGENT 1, GENERATION 6 (all ERROR, correctly) |
| app usage / billed | 0 calls, 0 tokens, **$0.00** / no generation record exists |
| exporter | `frames_enqueued=50 frames_dropped=0 observations_sent=35 http_errors=0 lookup_ok=0 lookup_failed=0` |

## B3 / D1 — the class now reaches every error observation

Passes 1 and 2 both failed this row: `metadata.error_class` was `None` everywhere
and no `statusMessage` named the class. At `58a1c0b`:

| observation | id | `metadata.error_class` | `statusMessage` begins |
| --- | --- | --- | --- |
| AGENT `Channel Sounder` | `a9ba1f503291bff6` | **`BadRequestError`** | `BadRequestError: Error code: 400 - …` |
| task SPAN | `e7f16220a4378c14` | **`BadRequestError`** | `BadRequestError: Error code: 400 - …` |
| node SPAN `sound_the_channel` | `58373c3b1d66f048` | **`BadRequestError`** | `BadRequestError: Error code: 400 - …` |
| run SPAN | `7ffeb0323f815b05` | **`BadRequestError`** | `BadRequestError: Error code: 400 - …` |
| `trace.output` | — | **`error_class: "BadRequestError"`** | `reason` also begins `BadRequestError: …` |

All four, plus the trace. The class is `BadRequestError`, which is what the app's
`NODE_END` frame carried in passes 1 and 2 and could not deliver.

### Every span still ends on its OWN closing frame

The commit holds an ERROR close that names no class and releases it once the node
supplies one — so the obvious risk is that the held spans acquire the *node's*
end time. They do not. Span `endTime` against the frames at that exact timestamp:

| observation | endTime | frames at that ts |
| --- | --- | --- |
| agent, task | `18:16:04.701Z` | seq 44, 45 — `AGENT_CALL` |
| node | `18:16:04.718Z` | seq 47, 48 — `NODE_END` |
| run | `18:16:04.721Z` | seq 49 — `WORKFLOW_END` |

Three distinct timestamps, each the frame that actually closes that level. The
agent and task still end 17 ms before the node and 20 ms before the run, exactly
as the frame log says they should.

Two frames now carry `error_class` where one did before (`NODE_END` seq **47 and
48**, and `WORKFLOW_END` seq **49**) — the serializer half of the same commit.
That is what lets the run span name the class directly instead of inheriting it.

## Still working from pass 2

- **`run_metrics.source = "exporter-tally"`**, `call_count: 6` — this run emits no
  `METRICS_UPDATED` frame, and the fallback still fills it and labels itself.
- **`open-spans.txt`**: `unfinished spans (non-EVENT observations with endTime
  null): 0` over 32 observations, with the three-way split printed beneath.

## Screenshot

`B3-failure.png` — AGENT `Channel Sounder` `a9ba1f503291bff6` open at
`…/traces/f371b3b96ca54b8b9f639c34249ef440?observation=a9ba1f503291bff6`. The
Error panel reads **`BadRequestError: Error code: 400 - …`** and the very first
Metadata row is **`error_class: "BadRequestError"`**. Compare
`../builder-agentfail-2/B3-failure.png`, the same view at `c608953`, where the
Error panel starts at `Error code: 400` and there is no `error_class` row at all.

The frame was checked after saving: the Langfuse project public key's bytes are
not in the PNG.
