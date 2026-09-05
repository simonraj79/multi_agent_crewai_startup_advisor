# Durations from Langfuse spans - run `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T14:42:19.727000Z -> 2026-09-05T14:42:25.753000Z (6.026 s)

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| (none) | 11 | 12.023 | 6.020 |  |
| Technical feasibility analyst | 3 | 6.014 | 2.005 |  |
| Market evidence analyst | 3 | 5.997 | 1.999 |  |
| Community demand analyst | 3 | 5.996 | 1.999 |  |
| Validation report writer | 2 | 0.000 | 0.000 |  |
| Startup validation synthesist | 2 | 0.000 | 0.000 |  |
| Startup validation scoper | 3 | 0.000 | 0.000 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| (none) | 11 | 12.023 | 6.020 |  |
| feasibility_task | 3 | 6.014 | 2.005 |  |
| market_task | 3 | 5.997 | 1.999 |  |
| sentiment_task | 3 | 5.996 | 1.999 |  |
| reporting_task | 2 | 0.000 | 0.000 |  |
| synthesis_task | 2 | 0.000 | 0.000 |  |
| scoping_task | 3 | 0.000 | 0.000 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| assess_technical_feasibility | 1 | 2.004 | 2.004 |  |
| research_market_landscape | 1 | 1.999 | 1.999 |  |
| analyze_community_sentiment | 1 | 1.998 | 1.998 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_feasibility | 4 | 8.019 | 2.005 |  |
| research_market | 4 | 7.996 | 1.999 |  |
| research_sentiment | 4 | 7.995 | 1.999 |  |
| (none) | 1 | 6.020 | 6.020 |  |
| persist | 1 | 0.000 | 0.000 |  |
| write_report | 3 | 0.000 | 0.000 |  |
| route_verdict | 1 | 0.000 | 0.000 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |
| synthesize | 3 | 0.000 | 0.000 |  |
| route_scope | 1 | 0.000 | 0.000 |  |
| confirm_scope | 1 | 0.000 | 0.000 |  |
| scope_idea | 3 | 0.000 | 0.000 |  |

## Slowest individual observations

| type | name | seconds | id |
| --- | --- | --- | --- |
| SPAN | run | 6.020 | 9ead1d3dd4cc2dcc |
| AGENT | Technical feasibility analyst | 2.005 | c268471fc550fc0f |
| SPAN | research_feasibility | 2.005 | a5029a841ef9e8a1 |
| SPAN | feasibility_task | 2.005 | 557d7f2c71b2da8f |
| TOOL | assess_technical_feasibility | 2.004 | 8aacb501648f9c00 |
| SPAN | sentiment_task | 1.999 | bed4a1b2aad8ef14 |
| SPAN | research_sentiment | 1.999 | c167d33de4847229 |
| AGENT | Community demand analyst | 1.999 | d390cec95bfae0e5 |
| SPAN | market_task | 1.999 | 3096aa6e7a841032 |
| SPAN | research_market | 1.999 | b0459be489c380bf |
| AGENT | Market evidence analyst | 1.999 | 44142966c5aa55d9 |
| TOOL | research_market_landscape | 1.999 | c75b32d29976070c |
| TOOL | analyze_community_sentiment | 1.998 | f9415efb15acd3b6 |
| SPAN | persist | 0.000 | f32c37c6c8f700c4 |
| GENERATION | google/gemini-3.5-flash-lite:nitro | 0.000 | 1f8c62745f0e065a |
| AGENT | Validation report writer | 0.000 | 990a42ee25ecbc81 |
| SPAN | reporting_task | 0.000 | 89c74b1397b7ed7f |
| SPAN | write_report | 0.000 | 58b6792ef119dbef |
| SPAN | route_verdict | 0.000 | ed749fbc45f00d90 |
| SPAN | review_verdict | 0.000 | 73d4c861a6ecf62f |
