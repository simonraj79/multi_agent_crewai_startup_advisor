# Langfuse figures - run `0813aacd-1550-4eca-b5be-c15ca29d5ffc`

| field | value |
| --- | --- |
| session found | yes |
| traces | 1 |
| trace names | ug_2805daab |
| environment | live |
| userId | teaching-proof |
| tags | gates:human, mode:run, ug_2805daab |
| trace output.status | completed |
| observations | 38 |
| observation types | AGENT:2, EVENT:22, GENERATION:2, SPAN:12 |
| observation roles | agent:2, event:22, generation:2, node:9, run:1, task:2 |
| unfinished spans (D3: non-EVENT, endTime null) | 0 |
| observations with endTime null, all types | 22 |
| of those, EVENT (no endTime by construction) | 22 |
| scores | 6 |
| wall clock (s) | 6.792 |

## Totals

| metric | value |
| --- | --- |
| generations | 2 |
| input tokens | 777 |
| output tokens | 473 |
| total tokens | 1250 |
| cost | $0.001416 |
| generations with no cost | 0 |
| tool observations | 0 |
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
| first observation visible after (s, from poll start) | 4.173 |
| count stable after (s, from poll start) | 4.173 |
| first visible after the run's terminal frame (s) | n/a |
| stable after the run's terminal frame (s) | n/a |
| stable within the timeout | yes |
| observation count at that point | 38 |
| generations at that point | 2 |
| of those, carrying the BILLED cost | 2 |
| of those, still on the app ESTIMATE | 0 |
| why the wait ended | every generation was billed - nothing left to change |
| stability window (s) | 5.000 |
| timeout (s) | 60.000 |
