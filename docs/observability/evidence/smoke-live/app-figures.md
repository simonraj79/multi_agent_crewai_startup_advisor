# App figures - run `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7`

Generated 2026-09-05T14:42:54Z from `http://127.0.0.1:8097`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T14:42:19.721535Z |
| completed_at | 2026-09-05T14:42:25.747708Z |
| wall clock (s) | 6.026 |
| frames downloaded | 97 |
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
| Technical feasibility analyst | 1 | 2.006 | 2.006 |  |
| Market evidence analyst | 1 | 2.001 | 2.001 |  |
| Community demand analyst | 1 | 2.001 | 2.001 |  |
| Validation report writer | 1 | 0.007 | 0.007 |  |
| Startup validation scoper | 1 | 0.002 | 0.002 |  |
| Startup validation synthesist | 1 | 0.002 | 0.002 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess_technical_feasibility | 1 | 2.005 | 2.005 |  |
| research_market_landscape | 1 | 2.001 | 2.001 |  |
| analyze_community_sentiment | 1 | 2.000 | 2.000 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_feasibility | 1 | 2.006 | 2.006 |  |
| research_market | 1 | 2.001 | 2.001 |  |
| research_sentiment | 1 | 2.001 | 2.001 |  |
| write_report | 1 | 0.007 | 0.007 |  |
| scope_idea | 1 | 0.002 | 0.002 |  |
| synthesize | 1 | 0.002 | 0.002 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

Unclosed app-side spans: **0**
