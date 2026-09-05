# Langfuse figures - run `f146e846-7e32-4276-9c9d-d79909a02eec`

| field | value |
| --- | --- |
| session found | yes |
| traces | 1 |
| trace names | idea-validator |
| environment | live |
| userId | proof-runner |
| tags | gates:auto, idea-validator, mode:run |
| trace output.status | completed |
| observations | 81 |
| observation types | AGENT:7, EVENT:42, GENERATION:11, SPAN:18, TOOL:3 |
| observation roles | agent:7, event:42, generation:11, node:11, run:1, task:6, tool:3 |
| unfinished spans (D3: non-EVENT, endTime null) | 0 |
| observations with endTime null, all types | 42 |
| of those, EVENT (no endTime by construction) | 42 |
| scores | 15 |
| wall clock (s) | 61.367 |

## Totals

| metric | value |
| --- | --- |
| generations | 11 |
| input tokens | 37379 |
| output tokens | 8678 |
| total tokens | 46057 |
| cost | $0.056977 |
| generations with no cost | 0 |
| tool observations | 3 |
| generation ids present | 11 |
| generations with no id | 0 |
| generations with the BILLED cost (`openrouter-billed`) | 11 |
| generations still on the app ESTIMATE | 0 |
| `cost_source` values seen | openrouter-billed:11 |
| DUPLICATE generation ids (E1) | 0 |

## Ingestion visibility (measured by polling, not assumed)

| field | value |
| --- | --- |
| polls | 1 |
| rate-limited polls (429) | 0 |
| other poll errors | 0 |
| first observation visible after (s, from poll start) | 1.843 |
| count stable after (s, from poll start) | 1.843 |
| first visible after the run's terminal frame (s) | 466.366 |
| stable after the run's terminal frame (s) | 466.366 |
| stable within the timeout | yes |
| observation count at that point | 81 |
| generations at that point | 11 |
| of those, carrying the BILLED cost | 11 |
| of those, still on the app ESTIMATE | 0 |
| why the wait ended | every generation was billed - nothing left to change |
| stability window (s) | 5.000 |
| timeout (s) | 300.000 |
