# Durations from Langfuse spans - run `c5d1dde9-c22d-4621-a171-9a7e85803105`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T16:42:11.474000Z -> 2026-09-05T16:42:35.502000Z (24.028 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 8.009 | 8.009 |  |
| Market evidence analyst | 1 | 8.003 | 8.003 |  |
| Technical feasibility analyst | 1 | 8.002 | 8.002 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |
| Startup validation synthesist | 1 | 0.000 | 0.000 |  |
| Validation report writer | 1 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sentiment_task | 1 | 8.009 | 8.009 |  |
| market_task | 1 | 8.004 | 8.004 |  |
| feasibility_task | 1 | 8.002 | 8.002 |  |
| scoping_task | 1 | 0.000 | 0.000 |  |
| synthesis_task | 1 | 0.000 | 0.000 |  |
| reporting_task | 1 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| analyze_community_sentiment | 1 | 8.008 | 8.008 |  |
| research_market_landscape | 1 | 8.002 | 8.002 |  |
| assess_technical_feasibility | 1 | 8.000 | 8.000 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_sentiment | 1 | 8.009 | 8.009 |  |
| research_market | 1 | 8.004 | 8.004 |  |
| research_feasibility | 1 | 8.002 | 8.002 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| synthesize | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| write_report | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Community demand analyst | 8.009 | 83594daa61c16d9e |
| task | sentiment_task | 8.009 | a2c10593c7c496a6 |
| tool | analyze_community_sentiment | 8.008 | e15c5e71fde34b19 |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 24.023 | 2bf9ef5fc2643df1 |
| agent | AGENT | Community demand analyst | 8.009 | 83594daa61c16d9e |
| node | SPAN | research_sentiment | 8.009 | 409d9c483506dc5e |
| task | SPAN | sentiment_task | 8.009 | a2c10593c7c496a6 |
| tool | TOOL | analyze_community_sentiment | 8.008 | e15c5e71fde34b19 |
| node | SPAN | research_market | 8.004 | 3194e114085d99a5 |
| task | SPAN | market_task | 8.004 | c34539a3bbfc74d4 |
| agent | AGENT | Market evidence analyst | 8.003 | 4df0bf14f12d9b36 |
| tool | TOOL | research_market_landscape | 8.002 | e04cda93482dac95 |
| agent | AGENT | Technical feasibility analyst | 8.002 | 8b1ac4e12e98820c |
| task | SPAN | feasibility_task | 8.002 | 4e06541d21cbd99a |
| node | SPAN | research_feasibility | 8.002 | afbd6c5cf84787a3 |
| tool | TOOL | assess_technical_feasibility | 8.000 | 7b8092e4f5e3eb41 |
| agent | AGENT | Startup validation scoper | 0.000 | 99bbf320d639eb85 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 27ce73898b3a1ded |
| node | SPAN | route_scope | 0.000 | 1e02a321820934fb |
| task | SPAN | scoping_task | 0.000 | 3139fe15ae29c338 |
| node | SPAN | scope_idea | 0.000 | bc0a6891b8bceb88 |
| node | SPAN | confirm_scope | 0.000 | ca5a1ae18c3f5305 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | d375fec2dfe855bc |
