# App figures - run `036ace4e-8b58-4a9b-9d46-0b78448684f9`

Generated 2026-09-05T15:14:52Z from `docs\observability\evidence\smoke-live\run-2\app-run.json (offline)`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T14:42:40.995664Z |
| completed_at | 2026-09-05T14:42:47.021110Z |
| wall clock (s) | 6.025 |
| frames downloaded | 96 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 6 |
| input tokens | 3840 |
| output tokens | 437 |
| total tokens | 4277 |
| cost (app estimate) | $0.002244 |
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
| output_tokens | 437 | 437 | yes |
| total_tokens | 4277 | 4277 | yes |
| cost_usd | 0.0022445 | 0.0022445 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 76 | 716 | $0.000382 |  |
| Market evidence analyst | 1 | 640 | 75 | 715 | $0.000380 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 74 | 714 | $0.000377 |  |
| Technical feasibility analyst | 1 | 640 | 76 | 716 | $0.000382 |  |
| Validation report writer | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 437 | 4277 | $0.002244 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 1 | 640 | 76 | 716 | $0.000382 |  |
| market_task | 1 | 640 | 75 | 715 | $0.000380 |  |
| reporting_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| scoping_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| sentiment_task | 1 | 640 | 76 | 716 | $0.000382 |  |
| synthesis_task | 1 | 640 | 74 | 714 | $0.000377 |  |
| **SUM** | 6 | 3840 | 437 | 4277 | $0.002244 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 1 | 640 | 76 | 716 | $0.000382 |  |
| research_market | 1 | 640 | 75 | 715 | $0.000380 |  |
| research_sentiment | 1 | 640 | 76 | 716 | $0.000382 |  |
| scope_idea | 1 | 640 | 68 | 708 | $0.000362 |  |
| synthesize | 1 | 640 | 74 | 714 | $0.000377 |  |
| write_report | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 437 | 4277 | $0.002244 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 6 | 3840 | 437 | 4277 | $0.002244 |  |
| **SUM** | 6 | 3840 | 437 | 4277 | $0.002244 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Market evidence analyst | 1 | 2.013 | 2.013 |  |
| Technical feasibility analyst | 1 | 2.006 | 2.006 |  |
| Community demand analyst | 1 | 2.001 | 2.001 |  |
| Startup validation synthesist | 1 | 0.001 | 0.001 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |
| Validation report writer | 1 | 0.000 | 0.000 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| - | - | - | - | - |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 2.013 | 2.013 |  |
| assess_technical_feasibility | 1 | 2.006 | 2.006 |  |
| analyze_community_sentiment | 1 | 2.001 | 2.001 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market | 1 | 2.013 | 2.013 |  |
| research_feasibility | 1 | 2.006 | 2.006 |  |
| research_sentiment | 1 | 2.001 | 2.001 |  |
| synthesize | 1 | 0.001 | 0.001 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| write_report | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

Unclosed app-side spans: **0**
