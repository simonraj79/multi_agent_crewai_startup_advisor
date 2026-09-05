# App figures - run `f4c8c779-52f2-40e1-9351-2668ea276ae4`

Generated 2026-09-05T16:34:55Z from `http://127.0.0.1:8000`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T16:33:04.211748Z |
| completed_at | 2026-09-05T16:33:54.540451Z |
| wall clock (s) | 50.329 |
| frames downloaded | 155 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 10 |
| input tokens | 29816 |
| output tokens | 6371 |
| total tokens | 36187 |
| cost (app estimate) | $0.038235 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 0 |
| tool calls (finished or errored) | 3 |
| generation ids captured | 10 |
| calls with no generation id | 0 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 10 | 10 | yes |
| input_tokens | 29816 | 29816 | yes |
| output_tokens | 6371 | 6371 | yes |
| total_tokens | 36187 | 36187 | yes |
| cost_usd | 0.03823525 | 0.03823525 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 2 | 4100 | 127 | 4227 | $0.001548 |  |
| Guardrail Agent | 1 | 2893 | 16 | 2909 | $0.002230 |  |
| Market evidence analyst | 2 | 5924 | 623 | 6547 | $0.003335 |  |
| Startup validation scoper | 1 | 1698 | 1417 | 3115 | $0.006587 |  |
| Startup validation synthesist | 1 | 6435 | 878 | 7313 | $0.008119 |  |
| Technical feasibility analyst | 2 | 4116 | 574 | 4690 | $0.002670 |  |
| Validation report writer | 1 | 4650 | 2736 | 7386 | $0.013747 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | 1 | 2893 | 16 | 2909 | $0.002230 |  |
| feasibility_task | 2 | 4116 | 574 | 4690 | $0.002670 |  |
| market_task | 2 | 5924 | 623 | 6547 | $0.003335 |  |
| reporting_task | 1 | 4650 | 2736 | 7386 | $0.013747 |  |
| scoping_task | 1 | 1698 | 1417 | 3115 | $0.006587 |  |
| sentiment_task | 2 | 4100 | 127 | 4227 | $0.001548 |  |
| synthesis_task | 1 | 6435 | 878 | 7313 | $0.008119 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 2 | 4116 | 574 | 4690 | $0.002670 |  |
| research_market | 2 | 5924 | 623 | 6547 | $0.003335 |  |
| research_sentiment | 2 | 4100 | 127 | 4227 | $0.001548 |  |
| scope_idea | 1 | 1698 | 1417 | 3115 | $0.006587 |  |
| synthesize | 1 | 6435 | 878 | 7313 | $0.008119 |  |
| write_report | 2 | 7543 | 2752 | 10295 | $0.015977 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 6 | 14140 | 1324 | 15464 | $0.007552 |  |
| google/gemini-3.8-flash | 4 | 15676 | 5047 | 20723 | $0.030683 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 1 | 16.633 | 16.633 |  |
| Startup validation scoper | 1 | 14.020 | 14.020 |  |
| Market evidence analyst | 1 | 6.690 | 6.690 |  |
| Technical feasibility analyst | 1 | 6.171 | 6.171 |  |
| Startup validation synthesist | 1 | 3.913 | 3.913 |  |
| Community demand analyst | 1 | 2.193 | 2.193 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| AgentExecutor | 7 | 51.873 | 16.628 |  |
| ReportCrew | 1 | 18.973 | 18.973 |  |
| reporting_task | 1 | 18.946 | 18.946 |  |
| ScopeCrew | 1 | 14.087 | 14.087 |  |
| scoping_task | 1 | 14.034 | 14.034 |  |
| MarketCrew | 1 | 6.722 | 6.722 |  |
| market_task | 1 | 6.696 | 6.696 |  |
| FeasibilityCrew | 1 | 6.464 | 6.464 |  |
| feasibility_task | 1 | 6.184 | 6.184 |  |
| SynthesisCrew | 1 | 3.935 | 3.935 |  |
| synthesis_task | 1 | 3.918 | 3.918 |  |
| SentimentCrew | 1 | 2.239 | 2.239 |  |
| sentiment_task | 1 | 2.202 | 2.202 |  |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 3.792 | 3.792 |  |
| assess_technical_feasibility | 1 | 3.537 | 3.537 |  |
| analyze_community_sentiment | 1 | 0.606 | 0.606 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 1 | 19.265 | 19.265 |  |
| scope_idea | 1 | 14.411 | 14.411 |  |
| research_market | 1 | 12.296 | 12.296 |  |
| research_feasibility | 1 | 9.389 | 9.389 |  |
| synthesize | 1 | 4.302 | 4.302 |  |
| research_sentiment | 1 | 2.658 | 2.658 |  |
| confirm_scope | 1 | 0.003 | 0.003 |  |
| review_verdict | 1 | 0.003 | 0.003 |  |
| route_scope | 1 | 0.002 | 0.002 |  |
| route_verdict | 1 | 0.002 | 0.002 |  |
| persist | 1 | 0.002 | 0.002 |  |

Unclosed app-side spans: **0**
