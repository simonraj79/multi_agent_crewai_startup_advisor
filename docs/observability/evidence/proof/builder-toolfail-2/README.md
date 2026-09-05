# `builder-toolfail-2` — re-proof of D2 at `c608953`, PAID

Run **2026-09-06** by V-PROOF, second pass, against **`c608953`**. Same backend
and rules as `../validator-live-2`; the published graph `ug_4e7e952f` was
re-launched unchanged, same request body as `../builder-toolfail`.

| | |
| --- | --- |
| app run id | `6342e33f-268e-4b67-87ae-1574a2fffbeb` |
| Langfuse trace id | `6342e33f268e4b6787ae1574a2fffbeb` |
| trace URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/6342e33f268e4b6787ae1574a2fffbeb` |
| workflow / gates / env | `ug_4e7e952f` / `auto` / `live`, user `proof-runner` |
| terminal | `failed`, 2.4 s |
| frames | 43 |
| observations | 21 — SPAN 6, EVENT 10, AGENT 1, GENERATION 2, TOOL 2 |
| app usage | 2 calls, 788 / 53 / 841 tokens, app estimate **$0.0003689** |
| OpenRouter billed | 2 generations, **$0.000369** |
| exporter | `frames_enqueued=43 frames_dropped=0 observations_sent=24 http_errors=0 lookup_ok=2 lookup_failed=0` |

## D2 — unchanged, still met

| what D2 asks | this run |
| --- | --- |
| a TOOL observation at `level=ERROR` with the error text | TOOL **`read_website_content`**, `ERROR`, `statusMessage: ValueError("Could not resolve hostname: 'sounding-line.invalid'")` |
| nested under the agent that called it | parent is AGENT **`Tidewater Cartographer`** `c380fc123b9d3852` |
| the agent's subsequent behaviour visible | `AGENT_CALL` ERROR then `NODE_END` ERROR — it gave up, matching `retry.max_retries: 0` / `on_error: "fail"` |

C2's names survive the re-run too: TOOL observations are
`['read_website_content', 'sounding_line_lookup']`, the second being the
author-named custom HTTP tool.

## FIXED here as well

- **Billed cost**: `cost_source = openrouter-billed` on **2 of 2**, both with
  `provider: "Google"`; `costDetails` `[0.0002075, 0.0001614]`, summing to the
  $0.000369 OpenRouter billed. `lookup_ok=2 lookup_failed=0`.
- **`run_metrics.source` = `app-snapshot`** — the labelled-source half of the
  same change, on a run that *did* emit a metrics snapshot.
- **`open-spans.txt`**: `unfinished spans (non-EVENT observations with endTime
  null): 0` over 21 observations (10 EVENTs open by construction).

## NOT FIXED — and here the class is absent from the TOOL as well

The orchestrator asked specifically whether "the tool's `ValueError` class is
also on the agent/task spans that closed on it". It is not, and neither is it on
the TOOL:

| observation | `metadata.error_class` |
| --- | --- |
| TOOL `read_website_content` | **None** |
| AGENT `Tidewater Cartographer` | **None** |
| task SPAN | **None** |
| node SPAN `chart_the_shoals` | **None** |
| run SPAN | **None** |
| `trace.output.error_class` | **null** |

The TOOL's `statusMessage` still *reads* `ValueError("Could not resolve
hostname: …")` — but only because the app's frame text is already a `repr`, which
was true before `c608953` too. Nothing is grouping on a class here.

Same measured cause as `../builder-agentfail-2`, and this run makes it plainer
because the exception class differs:

```text
frames carrying error_class: [(39, 'NODE_END', 'ToolExecutionFailedError')]   <- exactly one
```

and no span closes on it:

| observation | endTime | closing frame(s) | carries `error_class`? |
| --- | --- | --- | --- |
| tool | `17:25:43.201Z` | seq 34/35 `TOOL_CALL` | no |
| agent, task | `17:25:43.205Z` | seq 37 `AGENT_CALL` | no |
| node | `17:25:43.231Z` | seq 40 `NODE_END` | no |
| run | `17:25:43.233Z` | seq 41 `WORKFLOW_END` | no |

One frame in the run has the class; four different frames close the five error
observations, and not one of them is it.
