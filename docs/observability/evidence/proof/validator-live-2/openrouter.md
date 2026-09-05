# OpenRouter figures

Generated 2026-09-05T17:30:42Z. DoD E1 / E5, OpenRouter column.

Token counts here are OpenRouter's **native** counts; `tokens_prompt` /
`tokens_completion` are its normalised (GPT-tokeniser) figures and are
reported separately, because comparing a native count against the app's
provider-reported count is the like-for-like comparison and the
normalised one is not.

| metric | value |
| --- | --- |
| ids requested | 12 |
| records found | 12 |
| NOT found | 0 |
| input tokens (native) | 42194 |
| output tokens (native) | 9340 |
| total tokens (native) | 51534 |
| input tokens (normalised) | 40650 |
| output tokens (normalised) | 9020 |
| cost, billed | $0.064418 |
| upstream inference cost | $0.000000 |
| records with no cost | 0 |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite-20260721 | 7 | 17712 | 1956 | 19668 | $0.018366 |  |
| google/gemini-3.8-flash-20260902 | 5 | 24482 | 7384 | 31866 | $0.046051 |  |
| **SUM** | 12 | 42194 | 9340 | 51534 | $0.064418 |  |

## Per serving provider

| provider | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Google | 4 | 20355 | 4360 | 24715 | $0.031616 |  |
| Google AI Studio | 8 | 21839 | 4980 | 26819 | $0.032802 |  |
| **SUM** | 12 | 42194 | 9340 | 51534 | $0.064418 |  |

## Per call

| generation id | model | provider | in | out | cost | latency ms | finish |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gen-1788629156-3XYsoFWTXtEiPMhfehhc | google/gemini-3.8-flash-20260902 | Google | 1698 | 880 | $0.004574 | 2157 | stop |
| gen-1788629163-XQySxMkCBkeNpiJFTTqz | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 1770 | 25 | $0.001068 | 585 | tool_calls |
| gen-1788629163-pPG31Cb6q5dKyBNQw1nl | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2008 | 35 | $0.001242 | 706 | tool_calls |
| gen-1788629165-nhHWXCVmPYNPZCNEWdLO | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2134 | 88 | $0.001548 | 553 | stop |
| gen-1788629165-QUTry8cGceuAYPtYTRkM | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2723 | 31 | $0.001610 | 580 | tool_calls |
| gen-1788629167-uAQ8vxVhuQWHlwLB4nsY | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2377 | 556 | $0.003786 | 646 | stop |
| gen-1788629171-SgXqi4rp8j8tpLO2vyVw | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 3214 | 601 | $0.004440 | 590 | stop |
| gen-1788629172-I8ALCGX6wpNumCdHm4Rw | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 3486 | 620 | $0.004672 | 623 | stop |
| gen-1788629177-swgMZxXjAIKcqQzUBfZ0 | google/gemini-3.8-flash-20260902 | Google | 8056 | 700 | $0.008667 | 4597 | stop |
| gen-1788629183-89vm7slnZAc1bxW57xET | google/gemini-3.8-flash-20260902 | Google AI Studio | 4127 | 3024 | $0.014435 | 7202 | stop |
| gen-1788629204-OqEGCs46fj8PwSFLYqCg | google/gemini-3.8-flash-20260902 | Google | 7423 | 2764 | $0.015932 | 11207 | stop |
| gen-1788629216-blo3uqi8eVqjSydzfB0R | google/gemini-3.8-flash-20260902 | Google | 3178 | 16 | $0.002443 | 1476 | stop |
