# App figures - run `1a0bea14-ffb3-459d-b5fc-f714a76e5f71`

Generated 2026-09-05T17:30:18Z from `http://127.0.0.1:8000`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | idea-validator |
| graph_version | 9c6ca8a6fefbfffd |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T17:25:53.323709Z |
| completed_at | 2026-09-05T17:26:55.258622Z |
| wall clock (s) | 61.935 |
| frames downloaded | 178 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 12 |
| input tokens | 42194 |
| output tokens | 9340 |
| total tokens | 51534 |
| cost (app estimate) | $0.056255 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 0 |
| tool calls (finished or errored) | 3 |
| generation ids captured | 12 |
| calls with no generation id | 0 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 12 | 12 | yes |
| input_tokens | 42194 | 42194 | yes |
| output_tokens | 9340 | 9340 | yes |
| total_tokens | 51534 | 51534 | yes |
| cost_usd | 0.0562551 | 0.0562551 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 2 | 4142 | 123 | 4265 | $0.001550 |  |
| Guardrail Agent | 1 | 3178 | 16 | 3194 | $0.002443 |  |
| Market evidence analyst | 3 | 9423 | 1252 | 10675 | $0.005957 |  |
| Startup validation scoper | 1 | 1698 | 880 | 2578 | $0.004574 |  |
| Startup validation synthesist | 1 | 8056 | 700 | 8756 | $0.008667 |  |
| Technical feasibility analyst | 2 | 4147 | 581 | 4728 | $0.002697 |  |
| Validation report writer | 2 | 11550 | 5788 | 17338 | $0.030367 |  |
| **SUM** | 12 | 42194 | 9340 | 51534 | $0.056255 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | 1 | 3178 | 16 | 3194 | $0.002443 |  |
| feasibility_task | 2 | 4147 | 581 | 4728 | $0.002697 |  |
| market_task | 3 | 9423 | 1252 | 10675 | $0.005957 |  |
| reporting_task | 2 | 11550 | 5788 | 17338 | $0.030367 |  |
| scoping_task | 1 | 1698 | 880 | 2578 | $0.004574 |  |
| sentiment_task | 2 | 4142 | 123 | 4265 | $0.001550 |  |
| synthesis_task | 1 | 8056 | 700 | 8756 | $0.008667 |  |
| **SUM** | 12 | 42194 | 9340 | 51534 | $0.056255 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| research_feasibility | 2 | 4147 | 581 | 4728 | $0.002697 |  |
| research_market | 3 | 9423 | 1252 | 10675 | $0.005957 |  |
| research_sentiment | 2 | 4142 | 123 | 4265 | $0.001550 |  |
| scope_idea | 1 | 1698 | 880 | 2578 | $0.004574 |  |
| synthesize | 1 | 8056 | 700 | 8756 | $0.008667 |  |
| write_report | 3 | 14728 | 5804 | 20532 | $0.032811 |  |
| **SUM** | 12 | 42194 | 9340 | 51534 | $0.056255 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 7 | 17712 | 1956 | 19668 | $0.010204 |  |
| google/gemini-3.8-flash | 5 | 24482 | 7384 | 31866 | $0.046051 |  |
| **SUM** | 12 | 42194 | 9340 | 51534 | $0.056255 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 2 | 33.163 | 21.615 |  |
| Market evidence analyst | 2 | 9.043 | 7.057 |  |
| Startup validation scoper | 1 | 6.730 | 6.730 |  |
| Technical feasibility analyst | 1 | 6.209 | 6.209 |  |
| Startup validation synthesist | 1 | 4.989 | 4.989 |  |
| Community demand analyst | 1 | 2.823 | 2.823 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| AgentExecutor | 9 | 64.680 | 21.609 |  |
| ReportCrew | 1 | 34.986 | 34.986 |  |
| reporting_task | 1 | 34.968 | 34.968 |  |
| MarketCrew | 1 | 9.078 | 9.078 |  |
| market_task | 1 | 9.052 | 9.052 |  |
| ScopeCrew | 1 | 6.768 | 6.768 |  |
| scoping_task | 1 | 6.736 | 6.736 |  |
| FeasibilityCrew | 1 | 6.259 | 6.259 |  |
| feasibility_task | 1 | 6.214 | 6.214 |  |
| SynthesisCrew | 1 | 5.020 | 5.020 |  |
| synthesis_task | 1 | 4.994 | 4.994 |  |
| SentimentCrew | 1 | 2.862 | 2.862 |  |
| sentiment_task | 1 | 2.828 | 2.828 |  |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 4.412 | 4.412 |  |
| assess_technical_feasibility | 1 | 3.496 | 3.496 |  |
| analyze_community_sentiment | 1 | 0.745 | 0.745 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 1 | 35.336 | 35.336 |  |
| research_market | 1 | 14.198 | 14.198 |  |
| research_feasibility | 1 | 9.661 | 9.661 |  |
| scope_idea | 1 | 7.067 | 7.067 |  |
| synthesize | 1 | 5.298 | 5.298 |  |
| research_sentiment | 1 | 3.273 | 3.273 |  |
| review_verdict | 1 | 0.003 | 0.003 |  |
| persist | 1 | 0.003 | 0.003 |  |
| confirm_scope | 1 | 0.002 | 0.002 |  |
| route_verdict | 1 | 0.002 | 0.002 |  |
| route_scope | 1 | 0.001 | 0.001 |  |

Unclosed app-side spans: **0**
