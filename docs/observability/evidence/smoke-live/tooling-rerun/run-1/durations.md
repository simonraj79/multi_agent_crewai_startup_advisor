# Durations from Langfuse spans - run `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T14:42:19.727000Z -> 2026-09-05T14:42:25.753000Z (6.026 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Technical feasibility analyst | 1 | 2.005 | 2.005 |  |
| Market evidence analyst | 1 | 1.999 | 1.999 |  |
| Community demand analyst | 1 | 1.999 | 1.999 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |
| Startup validation synthesist | 1 | 0.000 | 0.000 |  |
| Validation report writer | 1 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| feasibility_task | 1 | 2.005 | 2.005 |  |
| market_task | 1 | 1.999 | 1.999 |  |
| sentiment_task | 1 | 1.999 | 1.999 |  |
| scoping_task | 1 | 0.000 | 0.000 |  |
| synthesis_task | 1 | 0.000 | 0.000 |  |
| reporting_task | 1 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess_technical_feasibility | 1 | 2.004 | 2.004 |  |
| research_market_landscape | 1 | 1.999 | 1.999 |  |
| analyze_community_sentiment | 1 | 1.998 | 1.998 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_feasibility | 1 | 2.005 | 2.005 |  |
| research_market | 1 | 1.999 | 1.999 |  |
| research_sentiment | 1 | 1.999 | 1.999 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| synthesize | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| write_report | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Technical feasibility analyst | 2.005 | c268471fc550fc0f |
| task | feasibility_task | 2.005 | 557d7f2c71b2da8f |
| tool | assess_technical_feasibility | 2.004 | 8aacb501648f9c00 |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 6.020 | 9ead1d3dd4cc2dcc |
| agent | AGENT | Technical feasibility analyst | 2.005 | c268471fc550fc0f |
| node | SPAN | research_feasibility | 2.005 | a5029a841ef9e8a1 |
| task | SPAN | feasibility_task | 2.005 | 557d7f2c71b2da8f |
| tool | TOOL | assess_technical_feasibility | 2.004 | 8aacb501648f9c00 |
| task | SPAN | market_task | 1.999 | 3096aa6e7a841032 |
| node | SPAN | research_market | 1.999 | b0459be489c380bf |
| agent | AGENT | Market evidence analyst | 1.999 | 44142966c5aa55d9 |
| tool | TOOL | research_market_landscape | 1.999 | c75b32d29976070c |
| task | SPAN | sentiment_task | 1.999 | bed4a1b2aad8ef14 |
| node | SPAN | research_sentiment | 1.999 | c167d33de4847229 |
| agent | AGENT | Community demand analyst | 1.999 | d390cec95bfae0e5 |
| tool | TOOL | analyze_community_sentiment | 1.998 | f9415efb15acd3b6 |
| node | SPAN | scope_idea | 0.000 | ba2bd058a7221478 |
| task | SPAN | scoping_task | 0.000 | c89c2a8db0d02938 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 057e7b99b18d69a9 |
| agent | AGENT | Startup validation scoper | 0.000 | 4026066f4d647fcf |
| node | SPAN | route_scope | 0.000 | b6f8ce01dab8e0b9 |
| node | SPAN | confirm_scope | 0.000 | eafcef350557ccc0 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | e21fdd6f4e89ae90 |
