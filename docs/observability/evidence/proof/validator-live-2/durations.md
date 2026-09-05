# Durations from Langfuse spans - run `1a0bea14-ffb3-459d-b5fc-f714a76e5f71`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T17:25:53.331000Z -> 2026-09-05T17:26:55.255000Z (61.924 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 1 | 33.162 | 33.162 |  |
| Market evidence analyst | 1 | 9.037 | 9.037 |  |
| Startup validation scoper | 1 | 6.722 | 6.722 |  |
| Technical feasibility analyst | 1 | 6.202 | 6.202 |  |
| Startup validation synthesist | 1 | 4.973 | 4.973 |  |
| Community demand analyst | 1 | 2.809 | 2.809 |  |
| Guardrail Agent | 1 | 1.786 | 1.786 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| reporting_task | 1 | 34.967 | 34.967 |  |
| market_task | 1 | 9.052 | 9.052 |  |
| scoping_task | 1 | 6.735 | 6.735 |  |
| feasibility_task | 1 | 6.214 | 6.214 |  |
| synthesis_task | 1 | 4.994 | 4.994 |  |
| sentiment_task | 1 | 2.828 | 2.828 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 4.409 | 4.409 |  |
| assess_technical_feasibility | 1 | 3.494 | 3.494 |  |
| analyze_community_sentiment | 1 | 0.745 | 0.745 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 1 | 35.335 | 35.335 |  |
| research_market | 1 | 14.197 | 14.197 |  |
| research_feasibility | 1 | 9.660 | 9.660 |  |
| scope_idea | 1 | 7.066 | 7.066 |  |
| synthesize | 1 | 5.297 | 5.297 |  |
| research_sentiment | 1 | 3.270 | 3.270 |  |
| persist | 1 | 0.003 | 0.003 |  |
| review_verdict | 1 | 0.002 | 0.002 |  |
| confirm_scope | 1 | 0.001 | 0.001 |  |
| route_scope | 1 | 0.001 | 0.001 |  |
| route_verdict | 1 | 0.001 | 0.001 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Validation report writer | 33.162 | be0b7a91b85ee023 |
| task | reporting_task | 34.967 | bed96be2956825cb |
| tool | research_market_landscape | 4.409 | b6e423a7097f2326 |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 61.924 | 589fbd68245bd87a |
| node | SPAN | write_report | 35.335 | ee7f6528d8be3d6b |
| task | SPAN | reporting_task | 34.967 | bed96be2956825cb |
| agent | AGENT | Validation report writer | 33.162 | be0b7a91b85ee023 |
| generation | GENERATION | google/gemini-3.8-flash | 21.585 | c0726a6f26cc213e |
| node | SPAN | research_market | 14.197 | 250b67de72386c6b |
| generation | GENERATION | google/gemini-3.8-flash | 11.518 | ed2b086e6cc8ff1d |
| node | SPAN | research_feasibility | 9.660 | b7c4818c08717d74 |
| task | SPAN | market_task | 9.052 | c3f2a6bb965c149f |
| agent | AGENT | Market evidence analyst | 9.037 | 19dafc57d7f1302a |
| node | SPAN | scope_idea | 7.066 | 1cc9b5d759c796a8 |
| task | SPAN | scoping_task | 6.735 | e86bdf48776ae6ac |
| agent | AGENT | Startup validation scoper | 6.722 | 32c6ab7679b129cc |
| generation | GENERATION | google/gemini-3.8-flash | 6.711 | 52218e11f6dfc640 |
| task | SPAN | feasibility_task | 6.214 | e65ca16c6b297bb8 |
| agent | AGENT | Technical feasibility analyst | 6.202 | 1f2e580dfb3d2c6b |
| node | SPAN | synthesize | 5.297 | 3f76ae1649ecca57 |
| task | SPAN | synthesis_task | 4.994 | 4dbbbab37a84d294 |
| agent | AGENT | Startup validation synthesist | 4.973 | fb881338a6d50423 |
| generation | GENERATION | google/gemini-3.8-flash | 4.962 | c7fae47588b2e4b7 |
