# Langfuse figures - run `f371b3b9-6ca5-4b8b-9f63-9c34249ef440`

| field | value |
| --- | --- |
| session found | yes |
| traces | 1 |
| trace names | ug_fd12e0a6 |
| environment | live |
| userId | proof-runner |
| tags | gates:auto, mode:run, ug_fd12e0a6 |
| trace output.status | failed |
| observations | 32 |
| observation types | AGENT:1, EVENT:19, GENERATION:6, SPAN:6 |
| observation roles | agent:1, event:19, generation:6, node:4, run:1, task:1 |
| unfinished spans (D3: non-EVENT, endTime null) | 0 |
| observations with endTime null, all types | 19 |
| of those, EVENT (no endTime by construction) | 19 |
| scores | 3 |
| wall clock (s) | 1.019 |

## Totals

| metric | value |
| --- | --- |
| generations | 6 |
| input tokens | 0 |
| output tokens | 0 |
| total tokens | 0 |
| cost | $0.000000 |
| generations with no cost | 6 |
| tool observations | 0 |
| generation ids present | 0 |
| generations with no id | 6 |
| generations with the BILLED cost (`openrouter-billed`) | 0 |
| generations still on the app ESTIMATE | 6 |
| `cost_source` values seen | app-estimate:6 |
| DUPLICATE generation ids (E1) | 0 |

## Ingestion visibility (measured by polling, not assumed)

| field | value |
| --- | --- |
| polls | 2 |
| rate-limited polls (429) | 0 |
| other poll errors | 0 |
| first observation visible after (s, from poll start) | 49.649 |
| count stable after (s, from poll start) | 55.118 |
| first visible after the run's terminal frame (s) | 80.277 |
| stable after the run's terminal frame (s) | 86.277 |
| stable within the timeout | yes |
| observation count at that point | 32 |
| generations at that point | 6 |
| of those, carrying the BILLED cost | 0 |
| of those, still on the app ESTIMATE | 6 |
| why the wait ended | both counts held across the stability window |
| stability window (s) | 5.000 |
| timeout (s) | 300.000 |
