# App figures - run `9d356fcb-aadd-4d41-ab06-7ffcd50c78ea`

Generated 2026-09-05T14:47:02Z from `http://127.0.0.1:8097`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T14:46:11.419257Z |
| completed_at | 2026-09-05T14:46:17.437575Z |
| wall clock (s) | 6.018 |
| frames downloaded | 96 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 6 |
| input tokens | 3840 |
| output tokens | 441 |
| total tokens | 4281 |
| cost (app estimate) | $0.002255 |
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
| output_tokens | 441 | 441 | yes |
| total_tokens | 4281 | 4281 | yes |
| cost_usd | 0.0022545000000000004 | 0.0022545 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 77 | 717 | $0.000385 |  |
| Market evidence analyst | 1 | 640 | 76 | 716 | $0.000382 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 75 | 715 | $0.000380 |  |
| Technical feasibility analyst | 1 | 640 | 77 | 717 | $0.000385 |  |
| Validation report writer | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 441 | 4281 | $0.002255 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 1 | 640 | 77 | 717 | $0.000385 |  |
| market_task | 1 | 640 | 76 | 716 | $0.000382 |  |
| reporting_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| scoping_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| sentiment_task | 1 | 640 | 77 | 717 | $0.000385 |  |
| synthesis_task | 1 | 640 | 75 | 715 | $0.000380 |  |
| **SUM** | 6 | 3840 | 441 | 4281 | $0.002255 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 1 | 640 | 77 | 717 | $0.000385 |  |
| research_market | 1 | 640 | 76 | 716 | $0.000382 |  |
| research_sentiment | 1 | 640 | 77 | 717 | $0.000385 |  |
| scope_idea | 1 | 640 | 68 | 708 | $0.000362 |  |
| synthesize | 1 | 640 | 75 | 715 | $0.000380 |  |
| write_report | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 441 | 4281 | $0.002255 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 6 | 3840 | 441 | 4281 | $0.002255 |  |
| **SUM** | 6 | 3840 | 441 | 4281 | $0.002255 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Technical feasibility analyst | 1 | 2.012 | 2.012 |  |
| Market evidence analyst | 1 | 2.002 | 2.002 |  |
| Community demand analyst | 1 | 2.001 | 2.001 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |
| Startup validation synthesist | 1 | 0.000 | 0.000 |  |
| Validation report writer | 1 | 0.000 | 0.000 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess_technical_feasibility | 1 | 2.011 | 2.011 |  |
| research_market_landscape | 1 | 2.002 | 2.002 |  |
| analyze_community_sentiment | 1 | 2.000 | 2.000 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_feasibility | 1 | 2.012 | 2.012 |  |
| research_market | 1 | 2.002 | 2.002 |  |
| research_sentiment | 1 | 2.002 | 2.002 |  |
| write_report | 1 | 0.001 | 0.001 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| synthesize | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

Unclosed app-side spans: **0**
