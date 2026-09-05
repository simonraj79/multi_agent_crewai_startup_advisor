# Durations from Langfuse spans - run `9d356fcb-aadd-4d41-ab06-7ffcd50c78ea`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T14:46:11.421000Z -> 2026-09-05T14:46:17.440000Z (6.019 s)

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| (none) | 11 | 12.028 | 6.016 |  |
| Technical feasibility analyst | 3 | 6.032 | 2.011 |  |
| Market evidence analyst | 3 | 6.000 | 2.000 |  |
| Community demand analyst | 3 | 5.999 | 2.000 |  |
| Validation report writer | 2 | 0.000 | 0.000 |  |
| Startup validation synthesist | 2 | 0.000 | 0.000 |  |
| Startup validation scoper | 3 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| (none) | 11 | 12.028 | 6.016 |  |
| feasibility_task | 3 | 6.032 | 2.011 |  |
| market_task | 3 | 6.000 | 2.000 |  |
| sentiment_task | 3 | 5.999 | 2.000 |  |
| reporting_task | 2 | 0.000 | 0.000 |  |
| synthesis_task | 2 | 0.000 | 0.000 |  |
| scoping_task | 3 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess_technical_feasibility | 1 | 2.010 | 2.010 |  |
| research_market_landscape | 1 | 2.000 | 2.000 |  |
| analyze_community_sentiment | 1 | 1.999 | 1.999 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_feasibility | 4 | 8.043 | 2.011 |  |
| research_sentiment | 4 | 8.000 | 2.001 |  |
| research_market | 4 | 8.000 | 2.000 |  |
| (none) | 1 | 6.016 | 6.016 |  |
| write_report | 3 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |
| synthesize | 3 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| scope_idea | 3 | 0.000 | 0.000 |  |

## Slowest individual observations

| type | name | seconds | id |
| --- | --- | --- | --- |
| SPAN | run | 6.016 | 2b82a696c0b6f0dd |
| AGENT | Technical feasibility analyst | 2.011 | 984acb2a3ad716a9 |
| SPAN | research_feasibility | 2.011 | 59ee61bed8bd97db |
| SPAN | feasibility_task | 2.011 | e264ef1a642917b8 |
| TOOL | assess_technical_feasibility | 2.010 | d0c49dcc6da23f6c |
| SPAN | research_sentiment | 2.001 | 2b0838a1f9f658f2 |
| AGENT | Community demand analyst | 2.000 | f6601de8db41d015 |
| SPAN | sentiment_task | 2.000 | 3aa826d29418e5b4 |
| AGENT | Market evidence analyst | 2.000 | 3a43fe40d03d5c13 |
| SPAN | research_market | 2.000 | 8d3c80066ed856b0 |
| SPAN | market_task | 2.000 | cd69ad9c5b62339f |
| TOOL | research_market_landscape | 2.000 | 9b60c97ced694ae9 |
| TOOL | analyze_community_sentiment | 1.999 | 86928232a1c47d12 |
| AGENT | Validation report writer | 0.000 | 3b7d65d51c1cdb99 |
| GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | b06a863ef1a8c1c4 |
| SPAN | write_report | 0.000 | 353d7ebd191e0d41 |
| SPAN | reporting_task | 0.000 | 5204bd15d590a845 |
| SPAN | persist | 0.000 | ffd83b6f93573bfc |
| AGENT | Startup validation synthesist | 0.000 | 803c407fb80109a8 |
| GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | d0cc1cc24dd9a538 |
