# Langfuse figures - run `f0297951-e1ff-49a1-90f6-725d06d9b112`

| field | value |
| --- | --- |
| session found | yes |
| traces | 1 |
| trace names | ug_4e7e952f |
| environment | live |
| userId | proof-runner |
| tags | gates:auto, mode:run, ug_4e7e952f |
| trace output.status | failed |
| observations | 21 |
| observation types | AGENT:1, EVENT:10, GENERATION:2, SPAN:6, TOOL:2 |
| observation roles | agent:1, event:10, generation:2, node:4, run:1, task:1, tool:2 |
| unfinished spans (D3: non-EVENT, endTime null) | 0 |
| observations with endTime null, all types | 10 |
| of those, EVENT (no endTime by construction) | 10 |
| scores | 3 |
| wall clock (s) | 2.732 |

## Totals

| metric | value |
| --- | --- |
| generations | 2 |
| input tokens | 788 |
| output tokens | 53 |
| total tokens | 841 |
| cost | $0.000369 |
| generations with no cost | 0 |
| tool observations | 2 |
| generation ids present | 2 |
| generations with no id | 0 |
| generations with the BILLED cost (`openrouter-billed`) | 2 |
| generations still on the app ESTIMATE | 0 |
| `cost_source` values seen | openrouter-billed:2 |
| DUPLICATE generation ids (E1) | 0 |

## Ingestion visibility (measured by polling, not assumed)

| field | value |
| --- | --- |
| polls | 1 |
| rate-limited polls (429) | 0 |
| other poll errors | 0 |
| first observation visible after (s, from poll start) | 2.551 |
| count stable after (s, from poll start) | 2.551 |
| first visible after the run's terminal frame (s) | 535.062 |
| stable after the run's terminal frame (s) | 535.062 |
| stable within the timeout | yes |
| observation count at that point | 21 |
| generations at that point | 2 |
| of those, carrying the BILLED cost | 2 |
| of those, still on the app ESTIMATE | 0 |
| why the wait ended | every generation was billed - nothing left to change |
| stability window (s) | 5.000 |
| timeout (s) | 300.000 |
