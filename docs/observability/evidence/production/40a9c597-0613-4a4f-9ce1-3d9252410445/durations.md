# Durations from Langfuse spans - run `40a9c597-0613-4a4f-9ce1-3d9252410445`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T22:33:07.966000Z -> 2026-09-05T22:33:57.901000Z (49.935 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 1 | 22.395 | 22.395 |  |
| Market evidence analyst | 1 | 10.403 | 10.403 |  |
| Community demand analyst | 1 | 7.219 | 7.219 |  |
| Startup validation scoper | 1 | 6.901 | 6.901 |  |
| Technical feasibility analyst | 1 | 5.503 | 5.503 |  |
| Startup validation synthesist | 1 | 3.413 | 3.413 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| reporting_task | 1 | 22.472 | 22.472 |  |
| market_task | 1 | 10.448 | 10.448 |  |
| sentiment_task | 1 | 7.247 | 7.247 |  |
| scoping_task | 1 | 6.917 | 6.917 |  |
| feasibility_task | 1 | 5.597 | 5.597 |  |
| synthesis_task | 1 | 3.502 | 3.502 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 5.454 | 5.454 |  |
| analyze_community_sentiment | 1 | 4.330 | 4.330 |  |
| assess_technical_feasibility | 1 | 3.257 | 3.257 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 1 | 22.691 | 22.691 |  |
| research_market | 1 | 15.561 | 15.561 |  |
| research_sentiment | 1 | 9.020 | 9.020 |  |
| research_feasibility | 1 | 9.011 | 9.011 |  |
| scope_idea | 1 | 7.157 | 7.157 |  |
| synthesize | 1 | 3.673 | 3.673 |  |
| route_verdict | 1 | 0.004 | 0.004 |  |
| persist | 1 | 0.003 | 0.003 |  |
| review_verdict | 1 | 0.002 | 0.002 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Validation report writer | 22.395 | 9f17938bde391355 |
| task | reporting_task | 22.472 | 520af9a337662d9f |
| tool | research_market_landscape | 5.454 | 5448a8bead1059dd |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 49.935 | 2bf69d7f01bd3ffb |
| node | SPAN | write_report | 22.691 | 39cf6b19bc627d41 |
| task | SPAN | reporting_task | 22.472 | 520af9a337662d9f |
| agent | AGENT | Validation report writer | 22.395 | 9f17938bde391355 |
| node | SPAN | research_market | 15.561 | e997300f7ff3099f |
| task | SPAN | market_task | 10.448 | e69bb5bfb8b9551c |
| agent | AGENT | Market evidence analyst | 10.403 | baeb4f2b1a03e118 |
| node | SPAN | research_sentiment | 9.020 | 2cc16e1dc82b741f |
| node | SPAN | research_feasibility | 9.011 | fd2a5dc0e43aea5d |
| generation | GENERATION | google/gemini-3.8-flash | 7.852 | 7d4c4d4a8591f95e |
| generation | GENERATION | google/gemini-3.8-flash | 7.310 | e531869fcb12846f |
| task | SPAN | sentiment_task | 7.247 | bec11fa8a46f6fff |
| agent | AGENT | Community demand analyst | 7.219 | 234bef72dd0ba93d |
| node | SPAN | scope_idea | 7.157 | 6640ecc9f3832d14 |
| generation | GENERATION | google/gemini-3.8-flash | 6.958 | b65aa437a4540c6d |
| task | SPAN | scoping_task | 6.917 | 2ef07fcb893db825 |
| agent | AGENT | Startup validation scoper | 6.901 | 35d3663c8f8b8f9c |
| generation | GENERATION | google/gemini-3.8-flash | 6.881 | 7af43ad4536aa4a6 |
| task | SPAN | feasibility_task | 5.597 | 138cfe011a4da54c |
| agent | AGENT | Technical feasibility analyst | 5.503 | f4d5ce4f5157e8d5 |
