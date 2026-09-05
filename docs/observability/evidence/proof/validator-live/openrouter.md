# OpenRouter figures

Generated 2026-09-05T16:37:30Z. DoD E1 / E5, OpenRouter column.

Token counts here are OpenRouter's **native** counts; `tokens_prompt` /
`tokens_completion` are its normalised (GPT-tokeniser) figures and are
reported separately, because comparing a native count against the app's
provider-reported count is the like-for-like comparison and the
normalised one is not.

| metric | value |
| --- | --- |
| ids requested | 10 |
| records found | 10 |
| NOT found | 0 |
| input tokens (native) | 29816 |
| output tokens (native) | 6371 |
| total tokens (native) | 36187 |
| input tokens (normalised) | 29975 |
| output tokens (normalised) | 5751 |
| cost, billed | $0.038235 |
| upstream inference cost | $0.000000 |
| records with no cost | 0 |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite-20260721 | 6 | 14140 | 1324 | 15464 | $0.007552 |  |
| google/gemini-3.8-flash-20260902 | 4 | 15676 | 5047 | 20723 | $0.030683 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Per serving provider

| provider | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Google | 3 | 9241 | 4169 | 13410 | $0.022564 |  |
| Google AI Studio | 7 | 20575 | 2202 | 22777 | $0.015671 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Per call

| generation id | model | provider | in | out | cost | latency ms | finish |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gen-1788625988-JC5jXfntDkNXlKRfCQQ2 | google/gemini-3.8-flash-20260902 | Google | 1698 | 1417 | $0.006587 | 3322 | stop |
| gen-1788626001-RrIs6P6CGSAzxkssdeZE | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 1987 | 35 | $0.000684 | 649 | tool_calls |
| gen-1788626002-u99P8rNsvheMHf1vkCL2 | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 1749 | 26 | $0.000590 | 586 | tool_calls |
| gen-1788626003-aGhyaFuo80K1x2AaImps | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2113 | 92 | $0.000864 | 582 | stop |
| gen-1788626004-8Lb063wT57oxD2uF5bvM | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2702 | 30 | $0.000886 | 652 | tool_calls |
| gen-1788626006-EJGlRLEqwNOM7rIY6Ss5 | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2367 | 548 | $0.002080 | 669 | stop |
| gen-1788626009-Jb6P3cjZRtxPEZco96RU | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 3222 | 593 | $0.002449 | 696 | stop |
| gen-1788626014-sOxLidalHnoL1ccrLsJO | google/gemini-3.8-flash-20260902 | Google AI Studio | 6435 | 878 | $0.008119 | 3485 | stop |
| gen-1788626018-aX3StVnB6NyyzA9qhPFS | google/gemini-3.8-flash-20260902 | Google | 4650 | 2736 | $0.013747 | 16234 | stop |
| gen-1788626035-SgCkpGZ9luExr8FBHOZZ | google/gemini-3.8-flash-20260902 | Google | 2893 | 16 | $0.002230 | 1956 | stop |
