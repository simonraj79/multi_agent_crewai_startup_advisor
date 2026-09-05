# Langfuse figures - run `1a0bea14-ffb3-459d-b5fc-f714a76e5f71`

| field | value |
| --- | --- |
| session found | yes |
| traces | 1 |
| trace names | idea-validator |
| environment | live |
| userId | proof-runner |
| tags | gates:auto, idea-validator, mode:run |
| trace output.status | completed |
| observations | 86 |
| observation types | AGENT:7, EVENT:46, GENERATION:12, SPAN:18, TOOL:3 |
| observation roles | agent:7, event:46, generation:12, node:11, run:1, task:6, tool:3 |
| unfinished spans (D3: non-EVENT, endTime null) | 0 |
| observations with endTime null, all types | 46 |
| of those, EVENT (no endTime by construction) | 46 |
| scores | 16 |
| wall clock (s) | 61.924 |

## Totals

| metric | value |
| --- | --- |
| generations | 12 |
| input tokens | 42194 |
| output tokens | 9340 |
| total tokens | 51534 |
| cost | $0.064418 |
| generations with no cost | 0 |
| tool observations | 3 |
| generation ids present | 12 |
| generations with no id | 0 |
| generations with the BILLED cost (`openrouter-billed`) | 12 |
| generations still on the app ESTIMATE | 0 |
| `cost_source` values seen | openrouter-billed:12 |
| DUPLICATE generation ids (E1) | 0 |

## Ingestion visibility (measured by polling, not assumed)

| field | value |
| --- | --- |
| polls | 1 |
| rate-limited polls (429) | 0 |
| other poll errors | 0 |
| first observation visible after (s, from poll start) | 3.325 |
| count stable after (s, from poll start) | 3.325 |
| first visible after the run's terminal frame (s) | 2457.742 |
| stable after the run's terminal frame (s) | 2457.742 |
| stable within the timeout | yes |
| observation count at that point | 86 |
| generations at that point | 12 |
| of those, carrying the BILLED cost | 12 |
| of those, still on the app ESTIMATE | 0 |
| why the wait ended | every generation was billed - nothing left to change |
| stability window (s) | 5.000 |
| timeout (s) | 300.000 |
