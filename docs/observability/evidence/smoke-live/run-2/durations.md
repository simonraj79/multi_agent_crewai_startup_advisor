# Durations from Langfuse spans - run `036ace4e-8b58-4a9b-9d46-0b78448684f9`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T14:42:40.999000Z -> 2026-09-05T14:42:47.023000Z (6.024 s)

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| (none) | 11 | 12.037 | 6.021 |  |
| Market evidence analyst | 3 | 6.033 | 2.011 |  |
| Technical feasibility analyst | 3 | 6.015 | 2.005 |  |
| Community demand analyst | 3 | 5.999 | 2.000 |  |
| Validation report writer | 2 | 0.000 | 0.000 |  |
| Startup validation synthesist | 2 | 0.000 | 0.000 |  |
| Startup validation scoper | 3 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| (none) | 11 | 12.037 | 6.021 |  |
| market_task | 3 | 6.033 | 2.011 |  |
| feasibility_task | 3 | 6.015 | 2.005 |  |
| sentiment_task | 3 | 5.999 | 2.000 |  |
| reporting_task | 2 | 0.000 | 0.000 |  |
| synthesis_task | 2 | 0.000 | 0.000 |  |
| scoping_task | 3 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 2.011 | 2.011 |  |
| assess_technical_feasibility | 1 | 2.005 | 2.005 |  |
| analyze_community_sentiment | 1 | 1.999 | 1.999 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market | 4 | 8.044 | 2.011 |  |
| research_feasibility | 4 | 8.020 | 2.005 |  |
| research_sentiment | 4 | 7.999 | 2.000 |  |
| (none) | 1 | 6.021 | 6.021 |  |
| write_report | 3 | 0.000 | 0.000 |  |
| persist | 1 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| synthesize | 3 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| scope_idea | 3 | 0.000 | 0.000 |  |

## Slowest individual observations

| type | name | seconds | id |
| --- | --- | --- | --- |
| SPAN | run | 6.021 | 173899aa04cf60b4 |
| SPAN | research_market | 2.011 | 91c00e33fc27a757 |
| AGENT | Market evidence analyst | 2.011 | fa8307eab5f43776 |
| TOOL | research_market_landscape | 2.011 | 0b66f5b27f495bb2 |
| SPAN | market_task | 2.011 | 05fb47aa3062afb4 |
| TOOL | assess_technical_feasibility | 2.005 | 602189eb01af2ed9 |
| SPAN | feasibility_task | 2.005 | fce1eb051067613f |
| AGENT | Technical feasibility analyst | 2.005 | 6d0136a3a9c131c3 |
| SPAN | research_feasibility | 2.005 | a51fa655cb8e8f80 |
| SPAN | sentiment_task | 2.000 | 71fbefd07a0a08b9 |
| AGENT | Community demand analyst | 2.000 | 814cd0218ca37a64 |
| SPAN | research_sentiment | 2.000 | f240db83aa528c12 |
| TOOL | analyze_community_sentiment | 1.999 | 341a61ba45549b9b |
| GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | dd51a39a0a8792ca |
| SPAN | write_report | 0.000 | ea4420874452c74f |
| SPAN | persist | 0.000 | dcedd578c154a1ee |
| SPAN | reporting_task | 0.000 | 68ea18f5103c97c8 |
| AGENT | Validation report writer | 0.000 | 5090c06335b85b1d |
| SPAN | route_verdict | 0.000 | 17b48bc4cf59b8e5 |
| SPAN | review_verdict | 0.000 | 074196e46f2a7751 |
