# Durations from Langfuse spans - run `f4c8c779-52f2-40e1-9351-2668ea276ae4`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T16:33:04.230000Z -> 2026-09-05T16:33:54.536000Z (50.306 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 1 | 16.626 | 16.626 |  |
| Startup validation scoper | 1 | 13.901 | 13.901 |  |
| Market evidence analyst | 1 | 6.680 | 6.680 |  |
| Technical feasibility analyst | 1 | 6.170 | 6.170 |  |
| Startup validation synthesist | 1 | 3.899 | 3.899 |  |
| Guardrail Agent | 1 | 2.296 | 2.296 |  |
| Community demand analyst | 1 | 2.186 | 2.186 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| reporting_task | 1 | 18.945 | 18.945 |  |
| scoping_task | 1 | 14.034 | 14.034 |  |
| market_task | 1 | 6.696 | 6.696 |  |
| feasibility_task | 1 | 6.183 | 6.183 |  |
| synthesis_task | 1 | 3.918 | 3.918 |  |
| sentiment_task | 1 | 2.202 | 2.202 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 3.789 | 3.789 |  |
| assess_technical_feasibility | 1 | 3.536 | 3.536 |  |
| analyze_community_sentiment | 1 | 0.605 | 0.605 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 9 | 19.264 | 19.264 | 8 |
| scope_idea | 7 | 14.410 | 14.410 | 6 |
| research_market | 7 | 12.296 | 12.296 | 6 |
| research_feasibility | 7 | 9.389 | 9.389 | 6 |
| synthesize | 7 | 4.300 | 4.300 | 6 |
| research_sentiment | 7 | 2.657 | 2.657 | 6 |
| confirm_scope | 1 | 0.003 | 0.003 |  |
| route_scope | 1 | 0.002 | 0.002 |  |
| review_verdict | 1 | 0.002 | 0.002 |  |
| route_verdict | 1 | 0.002 | 0.002 |  |
| persist | 1 | 0.001 | 0.001 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Validation report writer | 16.626 | 4601d7501c7fc493 |
| task | reporting_task | 18.945 | 7f838c91a5684b2a |
| tool | research_market_landscape | 3.789 | a6c68222501bc21d |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 50.306 | 5525de0c3601355d |
| node | SPAN | write_report | 19.264 | c0fa62409a92b0b0 |
| task | SPAN | reporting_task | 18.945 | 7f838c91a5684b2a |
| agent | AGENT | Validation report writer | 16.626 | 4601d7501c7fc493 |
| generation | GENERATION | google/gemini-3.8-flash | 16.600 | c5a7eed92550304e |
| node | SPAN | scope_idea | 14.410 | cd65f669d2eb6555 |
| task | SPAN | scoping_task | 14.034 | 6dfb83723296e78d |
| agent | AGENT | Startup validation scoper | 13.901 | d8f044a1aadf1806 |
| generation | GENERATION | google/gemini-3.8-flash | 13.888 | 06da27df751f0ebf |
| node | SPAN | research_market | 12.296 | 2df46cce0a7305da |
| node | SPAN | research_feasibility | 9.389 | 780033877dd975ad |
| task | SPAN | market_task | 6.696 | 24a7e1d59a77be61 |
| agent | AGENT | Market evidence analyst | 6.680 | 5110f385afb7793c |
| task | SPAN | feasibility_task | 6.183 | 17b86b77e236cbc3 |
| agent | AGENT | Technical feasibility analyst | 6.170 | a656aaa1076b568b |
| node | SPAN | synthesize | 4.300 | 0ebe23e34c2295b8 |
| task | SPAN | synthesis_task | 3.918 | efc9e2d1d24515b3 |
| agent | AGENT | Startup validation synthesist | 3.899 | f08d4270ed7ed45c |
| generation | GENERATION | google/gemini-3.8-flash | 3.885 | a07839dc6a12d3a3 |
| tool | TOOL | research_market_landscape | 3.789 | a6c68222501bc21d |
