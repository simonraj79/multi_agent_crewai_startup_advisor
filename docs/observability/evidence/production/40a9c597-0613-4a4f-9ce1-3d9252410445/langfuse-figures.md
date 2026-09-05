# Langfuse figures - run `40a9c597-0613-4a4f-9ce1-3d9252410445`

| field | value |
| --- | --- |
| session found | yes |
| traces | 1 |
| trace names | idea-validator |
| environment | live |
| userId | gkHdcQ0SRsnaVDWkCXD24AVvJ5vaFVVL |
| tags | gates:auto, idea-validator, mode:run |
| trace output.status | completed |
| observations | 87 |
| observation types | AGENT:6, EVENT:48, GENERATION:12, SPAN:18, TOOL:3 |
| observation roles | agent:6, event:48, generation:12, node:11, run:1, task:6, tool:3 |
| unfinished spans (D3: non-EVENT, endTime null) | 0 |
| observations with endTime null, all types | 48 |
| of those, EVENT (no endTime by construction) | 48 |
| scores | 17 |
| wall clock (s) | 49.935 |

## Totals

| metric | value |
| --- | --- |
| generations | 12 |
| input tokens | 48908 |
| output tokens | 14124 |
| total tokens | 63032 |
| cost | $0.087945 |
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
| first observation visible after (s, from poll start) | 7.247 |
| count stable after (s, from poll start) | 7.247 |
| first visible after the run's terminal frame (s) | 455.000 |
| stable after the run's terminal frame (s) | 455.000 |
| stable within the timeout | yes |
| observation count at that point | 87 |
| generations at that point | 12 |
| of those, carrying the BILLED cost | 12 |
| of those, still on the app ESTIMATE | 0 |
| why the wait ended | every generation was billed - nothing left to change |
| stability window (s) | 20.000 |
| timeout (s) | 300.000 |
