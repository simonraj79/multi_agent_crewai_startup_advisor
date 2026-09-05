# Durations from Langfuse spans - run `036ace4e-8b58-4a9b-9d46-0b78448684f9`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T14:42:40.999000Z -> 2026-09-05T14:42:47.023000Z (6.024 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Market evidence analyst | 1 | 2.011 | 2.011 |  |
| Technical feasibility analyst | 1 | 2.005 | 2.005 |  |
| Community demand analyst | 1 | 2.000 | 2.000 |  |
| Startup validation scoper | 1 | 0.000 | 0.000 |  |
| Startup validation synthesist | 1 | 0.000 | 0.000 |  |
| Validation report writer | 1 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| market_task | 1 | 2.011 | 2.011 |  |
| feasibility_task | 1 | 2.005 | 2.005 |  |
| sentiment_task | 1 | 2.000 | 2.000 |  |
| scoping_task | 1 | 0.000 | 0.000 |  |
| synthesis_task | 1 | 0.000 | 0.000 |  |
| reporting_task | 1 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 2.011 | 2.011 |  |
| assess_technical_feasibility | 1 | 2.005 | 2.005 |  |
| analyze_community_sentiment | 1 | 1.999 | 1.999 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market | 1 | 2.011 | 2.011 |  |
| research_feasibility | 1 | 2.005 | 2.005 |  |
| research_sentiment | 1 | 2.000 | 2.000 |  |
| scope_idea | 1 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| synthesize | 1 | 0.000 | 0.000 |  |
| write_report | 1 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Market evidence analyst | 2.011 | fa8307eab5f43776 |
| task | market_task | 2.011 | 05fb47aa3062afb4 |
| tool | research_market_landscape | 2.011 | 0b66f5b27f495bb2 |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 6.021 | 173899aa04cf60b4 |
| node | SPAN | research_market | 2.011 | 91c00e33fc27a757 |
| agent | AGENT | Market evidence analyst | 2.011 | fa8307eab5f43776 |
| tool | TOOL | research_market_landscape | 2.011 | 0b66f5b27f495bb2 |
| task | SPAN | market_task | 2.011 | 05fb47aa3062afb4 |
| tool | TOOL | assess_technical_feasibility | 2.005 | 602189eb01af2ed9 |
| task | SPAN | feasibility_task | 2.005 | fce1eb051067613f |
| agent | AGENT | Technical feasibility analyst | 2.005 | 6d0136a3a9c131c3 |
| node | SPAN | research_feasibility | 2.005 | a51fa655cb8e8f80 |
| task | SPAN | sentiment_task | 2.000 | 71fbefd07a0a08b9 |
| agent | AGENT | Community demand analyst | 2.000 | 814cd0218ca37a64 |
| node | SPAN | research_sentiment | 2.000 | f240db83aa528c12 |
| tool | TOOL | analyze_community_sentiment | 1.999 | 341a61ba45549b9b |
| agent | AGENT | Startup validation scoper | 0.000 | 87e3fce05d0359d6 |
| node | SPAN | scope_idea | 0.000 | 7ecc75955c106a2a |
| task | SPAN | scoping_task | 0.000 | 890c543fa8213174 |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | aaaf10d8c603df38 |
| node | SPAN | route_scope | 0.000 | 69296a2d952da2a4 |
| node | SPAN | confirm_scope | 0.000 | e26fffadb17d76aa |
| generation | GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 5af0c325fc94911d |
