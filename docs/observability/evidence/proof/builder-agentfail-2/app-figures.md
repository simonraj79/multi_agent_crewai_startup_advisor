# App figures - run `45cc3736-ed0b-466a-9dc6-e7f69ff0eea0`

Generated 2026-09-05T17:26:10Z from `http://127.0.0.1:8000`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | ug_fd12e0a6 |
| graph_version | 4a1ba2a50916d665 |
| status | failed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T17:25:31.842827Z |
| completed_at | 2026-09-05T17:25:33.991691Z |
| wall clock (s) | 2.149 |
| frames downloaded | 50 |
| error | Error code: 400 - {'error': {'message': "This endpoint's maximum context length is 1048576 tokens. However, you requested about 2000000311 tokens (311 of text input, 2000000000 in the output). Please reduce the length of either one, or use the context-compression plugin to compress your prompt automatically.", 'code': 400, 'metadata': {'provider_name': None}}} |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 0 |
| input tokens | 0 |
| output tokens | 0 |
| total tokens | 0 |
| cost (app estimate) | $0.000000 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 6 |
| tool calls (finished or errored) | 0 |
| generation ids captured | 0 |
| calls with no generation id | 0 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 0 | 0 | yes |
| input_tokens | 0 | 0 | yes |
| output_tokens | 0 | 0 | yes |
| total_tokens | 0 | 0 | yes |
| cost_usd | 0.0 | 0.0 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| **SUM** | 0 | 0 | 0 | 0 | $0.000000 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| **SUM** | 0 | 0 | 0 | 0 | $0.000000 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| **SUM** | 0 | 0 | 0 | 0 | $0.000000 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| **SUM** | 0 | 0 | 0 | 0 | $0.000000 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Channel Sounder | 3 | 0.896 | 0.649 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| crew | 1 | 0.948 | 0.948 |  |
| Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 1 | 0.935 | 0.935 |  |
| AgentExecutor | 3 | 0.852 | 0.643 |  |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sound_the_channel | 1 | 1.228 | 1.228 |  |
| start_sounding | 2 | 0.007 | 0.004 |  |
| the_brief | 1 | 0.005 | 0.005 |  |

Unclosed app-side spans: **0**
