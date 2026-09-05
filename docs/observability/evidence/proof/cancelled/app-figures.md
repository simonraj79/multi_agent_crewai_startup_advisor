# App figures - run `073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba`

Generated 2026-09-05T16:41:21Z from `http://127.0.0.1:8099`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | cancelled |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T16:41:08.322995Z |
| completed_at | 2026-09-05T16:41:14.474161Z |
| wall clock (s) | 6.151 |
| frames downloaded | 82 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 5 |
| input tokens | 3200 |
| output tokens | 452 |
| total tokens | 3652 |
| cost (app estimate) | $0.002090 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 0 |
| tool calls (finished or errored) | 3 |
| generation ids captured | 0 |
| calls with no generation id | 5 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 5 | 5 | yes |
| input_tokens | 3200 | 3200 | yes |
| output_tokens | 452 | 452 | yes |
| total_tokens | 3652 | 3652 | yes |
| cost_usd | 0.00209 | 0.00209 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 96 | 736 | $0.000432 |  |
| Market evidence analyst | 1 | 640 | 96 | 736 | $0.000432 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 95 | 735 | $0.000429 |  |
| Technical feasibility analyst | 1 | 640 | 97 | 737 | $0.000434 |  |
| **SUM** | 5 | 3200 | 452 | 3652 | $0.002090 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 1 | 640 | 97 | 737 | $0.000434 |  |
| market_task | 1 | 640 | 96 | 736 | $0.000432 |  |
| scoping_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| sentiment_task | 1 | 640 | 96 | 736 | $0.000432 |  |
| synthesis_task | 1 | 640 | 95 | 735 | $0.000429 |  |
| **SUM** | 5 | 3200 | 452 | 3652 | $0.002090 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 1 | 640 | 97 | 737 | $0.000434 |  |
| research_market | 1 | 640 | 96 | 736 | $0.000432 |  |
| research_sentiment | 1 | 640 | 96 | 736 | $0.000432 |  |
| scope_idea | 1 | 640 | 68 | 708 | $0.000362 |  |
| synthesize | 1 | 640 | 95 | 735 | $0.000429 |  |
| **SUM** | 5 | 3200 | 452 | 3652 | $0.002090 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 5 | 3200 | 452 | 3652 | $0.002090 |  |
| **SUM** | 5 | 3200 | 452 | 3652 | $0.002090 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Market evidence analyst | 1 | 6.147 | 6.147 |  |
| Startup validation scoper | 1 | 0.001 | 0.001 |  |
| Technical feasibility analyst | 1 | 0.001 | 0.001 |  |
| Community demand analyst | 1 | 0.000 | 0.000 |  |
| Startup validation synthesist | 1 | 0.000 | 0.000 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 6.146 | 6.146 |  |
| analyze_community_sentiment | 1 | 0.000 | 0.000 |  |
| assess_technical_feasibility | 1 | 0.000 | 0.000 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market | 1 | 6.147 | 6.147 |  |
| scope_idea | 1 | 0.001 | 0.001 |  |
| research_feasibility | 1 | 0.001 | 0.001 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| research_sentiment | 1 | 0.000 | 0.000 |  |
| synthesize | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |

Unclosed app-side spans: **0**
