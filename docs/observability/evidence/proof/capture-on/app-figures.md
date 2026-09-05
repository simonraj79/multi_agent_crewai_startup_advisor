# App figures - run `c5d1dde9-c22d-4621-a171-9a7e85803105`

Generated 2026-09-05T16:42:41Z from `http://127.0.0.1:8099`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T16:42:11.471636Z |
| completed_at | 2026-09-05T16:42:35.497817Z |
| wall clock (s) | 24.026 |
| frames downloaded | 98 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 6 |
| input tokens | 3840 |
| output tokens | 628 |
| total tokens | 4468 |
| cost (app estimate) | $0.002722 |
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
| output_tokens | 628 | 628 | yes |
| total_tokens | 4468 | 4468 | yes |
| cost_usd | 0.002722 | 0.002722 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 123 | 763 | $0.000500 |  |
| Market evidence analyst | 1 | 640 | 123 | 763 | $0.000500 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 122 | 762 | $0.000497 |  |
| Technical feasibility analyst | 1 | 640 | 124 | 764 | $0.000502 |  |
| Validation report writer | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 628 | 4468 | $0.002722 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 1 | 640 | 124 | 764 | $0.000502 |  |
| market_task | 1 | 640 | 123 | 763 | $0.000500 |  |
| reporting_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| scoping_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| sentiment_task | 1 | 640 | 123 | 763 | $0.000500 |  |
| synthesis_task | 1 | 640 | 122 | 762 | $0.000497 |  |
| **SUM** | 6 | 3840 | 628 | 4468 | $0.002722 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 1 | 640 | 124 | 764 | $0.000502 |  |
| research_market | 1 | 640 | 123 | 763 | $0.000500 |  |
| research_sentiment | 1 | 640 | 123 | 763 | $0.000500 |  |
| scope_idea | 1 | 640 | 68 | 708 | $0.000362 |  |
| synthesize | 1 | 640 | 122 | 762 | $0.000497 |  |
| write_report | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 628 | 4468 | $0.002722 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 6 | 3840 | 628 | 4468 | $0.002722 |  |
| **SUM** | 6 | 3840 | 628 | 4468 | $0.002722 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 8.010 | 8.010 |  |
| Market evidence analyst | 1 | 8.005 | 8.005 |  |
| Technical feasibility analyst | 1 | 8.003 | 8.003 |  |
| Startup validation scoper | 1 | 0.001 | 0.001 |  |
| Startup validation synthesist | 1 | 0.001 | 0.001 |  |
| Validation report writer | 1 | 0.001 | 0.001 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| analyze_community_sentiment | 1 | 8.009 | 8.009 |  |
| research_market_landscape | 1 | 8.004 | 8.004 |  |
| assess_technical_feasibility | 1 | 8.001 | 8.001 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_sentiment | 1 | 8.010 | 8.010 |  |
| research_market | 1 | 8.006 | 8.006 |  |
| research_feasibility | 1 | 8.003 | 8.003 |  |
| synthesize | 1 | 0.002 | 0.002 |  |
| scope_idea | 1 | 0.001 | 0.001 |  |
| write_report | 1 | 0.001 | 0.001 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

Unclosed app-side spans: **0**
