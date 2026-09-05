# Durations from Langfuse spans - run `073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T16:41:08.325000Z -> 2026-09-05T16:41:14.479000Z (6.154 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Market evidence analyst | 1 | 6.145 | 6.145 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |
| Community demand analyst | 1 | 0.000 | 0.000 |  |
| Technical feasibility analyst | 1 | 0.000 | 0.000 |  |
| Startup validation synthesist | 1 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| market_task | 1 | 6.145 | 6.145 |  |
| scoping_task | 1 | 0.000 | 0.000 |  |
| sentiment_task | 1 | 0.000 | 0.000 |  |
| feasibility_task | 1 | 0.000 | 0.000 |  |
| synthesis_task | 1 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 6.144 | 6.144 |  |
| analyze_community_sentiment | 1 | 0.000 | 0.000 |  |
| assess_technical_feasibility | 1 | 0.000 | 0.000 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market | 1 | 6.145 | 6.145 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| research_sentiment | 1 | 0.000 | 0.000 |  |
| research_feasibility | 1 | 0.000 | 0.000 |  |
| synthesize | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Market evidence analyst | 6.145 | e25b4ade921f6423 |
| task | market_task | 6.145 | 4100d0e1a9b5d647 |
| tool | research_market_landscape | 6.144 | bf2d3a5b430b44af |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 6.149 | 894a7799f1ecc335 |
| agent | AGENT | Market evidence analyst | 6.145 | e25b4ade921f6423 |
| node | SPAN | research_market | 6.145 | 39e6a1439e69b1eb |
| task | SPAN | market_task | 6.145 | 4100d0e1a9b5d647 |
| tool | TOOL | research_market_landscape | 6.144 | bf2d3a5b430b44af |
| agent | AGENT | Startup validation scoper | 0.000 | bde2e036b0d06d97 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 246fb94fcdf1e9f6 |
| node | SPAN | confirm_scope | 0.000 | 24635e3c44bdee5a |
| task | SPAN | scoping_task | 0.000 | 8e7863fe37269e04 |
| node | SPAN | scope_idea | 0.000 | d47445c857474b11 |
| node | SPAN | route_scope | 0.000 | 094802ac8aab3d76 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 345030b867aec1e0 |
| agent | AGENT | Community demand analyst | 0.000 | 1e575158d32f7d05 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 7ed3de5e5a7f8618 |
| node | SPAN | research_sentiment | 0.000 | aac7f62aa6a89f8c |
| task | SPAN | sentiment_task | 0.000 | d1f0905227e2ad0e |
| tool | TOOL | analyze_community_sentiment | 0.000 | ee0cd27de6f33283 |
| agent | AGENT | Technical feasibility analyst | 0.000 | f47b98aa5493aad9 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 7e2337cc603154ad |
| node | SPAN | research_feasibility | 0.000 | 1d9feae750ac95d1 |
