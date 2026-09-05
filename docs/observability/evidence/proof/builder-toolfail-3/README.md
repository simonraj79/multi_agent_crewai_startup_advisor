# `builder-toolfail-3` — D2 at `58a1c0b`, PAID, and the other half of the A2 pair

Run **2026-09-06** by V-PROOF, third pass, against **`58a1c0b`**. Launched
**5 ms** after `../validator-live-3` — `../concurrent-3/launch-times.txt`. Same
document and request body as `../builder-toolfail`.

| | |
| --- | --- |
| app run id | `f0297951-e1ff-49a1-90f6-725d06d9b112` |
| Langfuse trace id | `f0297951e1ff49a190f6725d06d9b112` |
| trace URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/f0297951e1ff49a190f6725d06d9b112` |
| workflow / gates / env / user | `ug_4e7e952f` / `auto` / `live` / `proof-runner` |
| terminal | `failed`, 2.4 s |
| frames | 44 |
| observations | 21 — SPAN 6, EVENT 10, AGENT 1, GENERATION 2, TOOL 2 |
| app usage | 2 calls, 788 / 53 / 841 tokens, estimate **$0.0003689** |
| OpenRouter billed | 2 generations, **$0.000369** |
| exporter | `frames_enqueued=44 frames_dropped=0 observations_sent=24 http_errors=0 lookup_ok=2 lookup_failed=0` |

## D2 — met, and now with the class as a field

| what D2 asks | this run |
| --- | --- |
| a TOOL observation at `level=ERROR` with the error text | TOOL **`read_website_content`** `ab6378130d772e46`, `ERROR`, `statusMessage: ValueError: ValueError("Could not resolve hostname: 'sounding-line.invalid'")`, **`metadata.error_class: "ValueError"`** |
| nested under the agent that called it | parent is AGENT **`Tidewater Cartographer`** `7c527ecb44053432` |
| the agent's subsequent behaviour visible | `AGENT_CALL` ERROR then `NODE_END` ERROR — it gave up, matching `retry.max_retries: 0` / `on_error: "fail"` |

The whole failing chain now names its class:

```text
TOOL   read_website_content    ERROR    error_class = ValueError
AGENT  Tidewater Cartographer  ERROR    error_class = ToolExecutionFailedError
SPAN   (task)                  ERROR    error_class = ToolExecutionFailedError
SPAN   chart_the_shoals        ERROR    error_class = ToolExecutionFailedError
SPAN   run                     ERROR    error_class = ToolExecutionFailedError   (parent: none - the root)
trace.output                            error_class = ToolExecutionFailedError
```

Two classes, correctly distinguished: the tool raised `ValueError`, and what
escaped the step was CrewAI's `ToolExecutionFailedError`. Passes 1 and 2 named
neither.

C2's invented names survive the re-run: the TOOL observations are
`read_website_content` and **`sounding_line_lookup`**, the second being the
author-named custom HTTP tool, at `DEFAULT` because it reports rather than raises.

## Regression #12 closed — a successful generation is not marked failed

The orchestrator's specific check. **Both** generations:

| | |
| --- | --- |
| `level` | **`DEFAULT`** on 2 of 2 |
| `metadata.cost_source` | **`openrouter-billed`** on 2 of 2 |
| `costDetails.total` | `0.0002075` and `0.0001614`, summing to the $0.000369 OpenRouter billed |
| `metadata.error_class` | `None` on both — correctly, they did not fail |

So on a run that failed, the two calls that **succeeded** and were still waiting
on their deferred price are no longer swept to `ERROR` by the terminal, while the
run span itself is `ERROR`. Both halves are visible in one screenshot.

`open-spans.txt`: `unfinished spans (non-EVENT observations with endTime null): 0`
over 21 observations (10 EVENTs, open by construction).

## Screenshot

`D2-tool-error.png` — TOOL `read_website_content` `ab6378130d772e46` open at
`…?observation=ab6378130d772e46`. It shows the ERROR badge, the Error panel
naming `ValueError`, `metadata.error_class: "ValueError"`,
`observation_role: "tool"`, and `input` as `arg_keys` / `arg_chars` /
`arg_fingerprint` under the default content policy. Beside it the tree shows the
two generations in plain type with their costs — not ERROR — under
`Tidewater Cartographer`, with `sounding_line_lookup` between them, and the
failing chain in red above.

## One cosmetic note, not a defect

The TOOL's `statusMessage` reads `ValueError: ValueError("Could not resolve
hostname: …")` — the class is prefixed onto a message that is already a `repr`
beginning with the class. §4 asks for `ExceptionClass: redacted message` and this
satisfies it; it just reads twice. The other four observations do not have this,
because their frame text is a sentence rather than a repr.
