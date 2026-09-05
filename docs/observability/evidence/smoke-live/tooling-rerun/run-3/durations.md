# Durations from Langfuse spans - run `9d356fcb-aadd-4d41-ab06-7ffcd50c78ea`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T14:46:11.421000Z -> 2026-09-05T14:46:17.440000Z (6.019 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Technical feasibility analyst | 1 | 2.011 | 2.011 |  |
| Market evidence analyst | 1 | 2.000 | 2.000 |  |
| Community demand analyst | 1 | 2.000 | 2.000 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |
| Startup validation synthesist | 1 | 0.000 | 0.000 |  |
| Validation report writer | 1 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| feasibility_task | 1 | 2.011 | 2.011 |  |
| market_task | 1 | 2.000 | 2.000 |  |
| sentiment_task | 1 | 2.000 | 2.000 |  |
| scoping_task | 1 | 0.000 | 0.000 |  |
| synthesis_task | 1 | 0.000 | 0.000 |  |
| reporting_task | 1 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess_technical_feasibility | 1 | 2.010 | 2.010 |  |
| research_market_landscape | 1 | 2.000 | 2.000 |  |
| analyze_community_sentiment | 1 | 1.999 | 1.999 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_feasibility | 1 | 2.011 | 2.011 |  |
| research_sentiment | 1 | 2.001 | 2.001 |  |
| research_market | 1 | 2.000 | 2.000 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| synthesize | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| write_report | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Technical feasibility analyst | 2.011 | 984acb2a3ad716a9 |
| task | feasibility_task | 2.011 | e264ef1a642917b8 |
| tool | assess_technical_feasibility | 2.010 | d0c49dcc6da23f6c |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 6.016 | 2b82a696c0b6f0dd |
| node | SPAN | research_feasibility | 2.011 | 59ee61bed8bd97db |
| task | SPAN | feasibility_task | 2.011 | e264ef1a642917b8 |
| agent | AGENT | Technical feasibility analyst | 2.011 | 984acb2a3ad716a9 |
| tool | TOOL | assess_technical_feasibility | 2.010 | d0c49dcc6da23f6c |
| node | SPAN | research_sentiment | 2.001 | 2b0838a1f9f658f2 |
| node | SPAN | research_market | 2.000 | 8d3c80066ed856b0 |
| task | SPAN | market_task | 2.000 | cd69ad9c5b62339f |
| tool | TOOL | research_market_landscape | 2.000 | 9b60c97ced694ae9 |
| agent | AGENT | Market evidence analyst | 2.000 | 3a43fe40d03d5c13 |
| task | SPAN | sentiment_task | 2.000 | 3aa826d29418e5b4 |
| agent | AGENT | Community demand analyst | 2.000 | f6601de8db41d015 |
| tool | TOOL | analyze_community_sentiment | 1.999 | 86928232a1c47d12 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | feb0f6acc0c263d0 |
| task | SPAN | scoping_task | 0.000 | 65b213a5430aed24 |
| node | SPAN | scope_idea | 0.000 | 902f0e251961881a |
| agent | AGENT | Startup validation scoper | 0.000 | e76badd421b3c57b |
| node | SPAN | confirm_scope | 0.000 | ab7ee24395f2b2ba |
| node | SPAN | route_scope | 0.000 | f84531f6cb0c92f7 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 06772630abaeed44 |
