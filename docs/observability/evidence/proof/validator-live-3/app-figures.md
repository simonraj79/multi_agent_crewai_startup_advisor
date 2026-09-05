# App figures - run `f146e846-7e32-4276-9c9d-d79909a02eec`

Generated 2026-09-05T18:16:14Z from `http://127.0.0.1:8000`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T18:07:35.246131Z |
| completed_at | 2026-09-05T18:08:36.634608Z |
| wall clock (s) | 61.388 |
| frames downloaded | 167 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 11 |
| input tokens | 37379 |
| output tokens | 8678 |
| total tokens | 46057 |
| cost (app estimate) | $0.052690 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 0 |
| tool calls (finished or errored) | 3 |
| generation ids captured | 11 |
| calls with no generation id | 0 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 11 | 11 | yes |
| input_tokens | 37379 | 37379 | yes |
| output_tokens | 8678 | 8678 | yes |
| total_tokens | 46057 | 46057 | yes |
| cost_usd | 0.05268975 | 0.05268975 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 2 | 4032 | 104 | 4136 | $0.001470 |  |
| Guardrail Agent | 1 | 3000 | 10 | 3010 | $0.002288 |  |
| Market evidence analyst | 2 | 5692 | 704 | 6396 | $0.003468 |  |
| Startup validation scoper | 1 | 1698 | 1188 | 2886 | $0.005729 |  |
| Startup validation synthesist | 1 | 7938 | 583 | 8521 | $0.008140 |  |
| Technical feasibility analyst | 2 | 3736 | 656 | 4392 | $0.002761 |  |
| Validation report writer | 2 | 11283 | 5433 | 16716 | $0.028836 |  |
| **SUM** | 11 | 37379 | 8678 | 46057 | $0.052690 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | 1 | 3000 | 10 | 3010 | $0.002288 |  |
| feasibility_task | 2 | 3736 | 656 | 4392 | $0.002761 |  |
| market_task | 2 | 5692 | 704 | 6396 | $0.003468 |  |
| reporting_task | 2 | 11283 | 5433 | 16716 | $0.028836 |  |
| scoping_task | 1 | 1698 | 1188 | 2886 | $0.005729 |  |
| sentiment_task | 2 | 4032 | 104 | 4136 | $0.001470 |  |
| synthesis_task | 1 | 7938 | 583 | 8521 | $0.008140 |  |
| **SUM** | 11 | 37379 | 8678 | 46057 | $0.052690 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 2 | 3736 | 656 | 4392 | $0.002761 |  |
| research_market | 2 | 5692 | 704 | 6396 | $0.003468 |  |
| research_sentiment | 2 | 4032 | 104 | 4136 | $0.001470 |  |
| scope_idea | 1 | 1698 | 1188 | 2886 | $0.005729 |  |
| synthesize | 1 | 7938 | 583 | 8521 | $0.008140 |  |
| write_report | 3 | 14283 | 5443 | 19726 | $0.031124 |  |
| **SUM** | 11 | 37379 | 8678 | 46057 | $0.052690 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 6 | 13460 | 1464 | 14924 | $0.007698 |  |
| google/gemini-3.8-flash | 5 | 23919 | 7214 | 31133 | $0.044992 |  |
| **SUM** | 11 | 37379 | 8678 | 46057 | $0.052690 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 2 | 27.844 | 14.680 |  |
| Startup validation scoper | 1 | 10.000 | 10.000 |  |
| Market evidence analyst | 1 | 9.881 | 9.881 |  |
| Technical feasibility analyst | 1 | 7.904 | 7.904 |  |
| Startup validation synthesist | 1 | 5.248 | 5.248 |  |
| Community demand analyst | 1 | 3.314 | 3.314 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| AgentExecutor | 8 | 65.777 | 14.674 |  |
| ReportCrew | 1 | 29.593 | 29.593 |  |
| reporting_task | 1 | 29.568 | 29.568 |  |
| ScopeCrew | 1 | 10.062 | 10.062 |  |
| scoping_task | 1 | 10.007 | 10.007 |  |
| MarketCrew | 1 | 9.942 | 9.942 |  |
| market_task | 1 | 9.886 | 9.886 |  |
| FeasibilityCrew | 1 | 8.218 | 8.218 |  |
| feasibility_task | 1 | 7.910 | 7.910 |  |
| SynthesisCrew | 1 | 5.281 | 5.281 |  |
| synthesis_task | 1 | 5.253 | 5.253 |  |
| SentimentCrew | 1 | 3.345 | 3.345 |  |
| sentiment_task | 1 | 3.320 | 3.320 |  |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 6.119 | 6.119 |  |
| assess_technical_feasibility | 1 | 4.001 | 4.001 |  |
| analyze_community_sentiment | 1 | 1.864 | 1.864 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 1 | 29.877 | 29.877 |  |
| research_market | 1 | 15.500 | 15.500 |  |
| research_feasibility | 1 | 10.783 | 10.783 |  |
| scope_idea | 1 | 10.379 | 10.379 |  |
| synthesize | 1 | 5.563 | 5.563 |  |
| research_sentiment | 1 | 3.755 | 3.755 |  |
| confirm_scope | 1 | 0.002 | 0.002 |  |
| review_verdict | 1 | 0.002 | 0.002 |  |
| route_verdict | 1 | 0.002 | 0.002 |  |
| persist | 1 | 0.002 | 0.002 |  |
| route_scope | 1 | 0.001 | 0.001 |  |

Unclosed app-side spans: **0**
