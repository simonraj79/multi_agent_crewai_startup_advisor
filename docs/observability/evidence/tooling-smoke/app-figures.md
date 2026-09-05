# App figures - run `54a93dc8-13e3-4edf-b180-af206f1eb168`

Generated 2026-09-05T13:36:30Z from `http://127.0.0.1:8098`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T13:35:29.470212Z |
| completed_at | 2026-09-05T13:35:35.502912Z |
| wall clock (s) | 6.033 |
| frames downloaded | 96 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 6 |
| input tokens | 3840 |
| output tokens | 449 |
| total tokens | 4289 |
| cost (app estimate) | $0.002275 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 0 |
| tool calls (finished or errored) | 3 |
| generation ids captured | 0 |
| calls with no generation id | 6 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 6 | 6 | yes |
| input_tokens | 3840 | 3840 | yes |
| output_tokens | 449 | 449 | yes |
| total_tokens | 4289 | 4289 | yes |
| cost_usd | 0.0022745 | 0.0022745 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 79 | 719 | $0.000389 |  |
| Market evidence analyst | 1 | 640 | 78 | 718 | $0.000387 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 77 | 717 | $0.000385 |  |
| Technical feasibility analyst | 1 | 640 | 79 | 719 | $0.000389 |  |
| Validation report writer | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 449 | 4289 | $0.002275 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 1 | 640 | 79 | 719 | $0.000389 |  |
| market_task | 1 | 640 | 78 | 718 | $0.000387 |  |
| reporting_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| scoping_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| sentiment_task | 1 | 640 | 79 | 719 | $0.000389 |  |
| synthesis_task | 1 | 640 | 77 | 717 | $0.000385 |  |
| **SUM** | 6 | 3840 | 449 | 4289 | $0.002275 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 1 | 640 | 79 | 719 | $0.000389 |  |
| research_market | 1 | 640 | 78 | 718 | $0.000387 |  |
| research_sentiment | 1 | 640 | 79 | 719 | $0.000389 |  |
| scope_idea | 1 | 640 | 68 | 708 | $0.000362 |  |
| synthesize | 1 | 640 | 77 | 717 | $0.000385 |  |
| write_report | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 449 | 4289 | $0.002275 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 6 | 3840 | 449 | 4289 | $0.002275 |  |
| **SUM** | 6 | 3840 | 449 | 4289 | $0.002275 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 2.008 | 2.008 |  |
| Technical feasibility analyst | 1 | 2.008 | 2.008 |  |
| Market evidence analyst | 1 | 2.005 | 2.005 |  |
| Startup validation synthesist | 1 | 0.001 | 0.001 |  |
| Validation report writer | 1 | 0.001 | 0.001 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| analyze_community_sentiment | 1 | 2.007 | 2.007 |  |
| assess_technical_feasibility | 1 | 2.007 | 2.007 |  |
| research_market_landscape | 1 | 2.004 | 2.004 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_sentiment | 1 | 2.008 | 2.008 |  |
| research_feasibility | 1 | 2.008 | 2.008 |  |
| research_market | 1 | 2.005 | 2.005 |  |
| synthesize | 1 | 0.002 | 0.002 |  |
| write_report | 1 | 0.001 | 0.001 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

Unclosed app-side spans: **0**
