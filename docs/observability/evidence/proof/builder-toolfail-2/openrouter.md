# OpenRouter figures

Generated 2026-09-05T17:30:42Z. DoD E1 / E5, OpenRouter column.

Token counts here are OpenRouter's **native** counts; `tokens_prompt` /
`tokens_completion` are its normalised (GPT-tokeniser) figures and are
reported separately, because comparing a native count against the app's
provider-reported count is the like-for-like comparison and the
normalised one is not.

| metric | value |
| --- | --- |
| ids requested | 2 |
| records found | 2 |
| NOT found | 0 |
| input tokens (native) | 788 |
| output tokens (native) | 53 |
| total tokens (native) | 841 |
| input tokens (normalised) | 1036 |
| output tokens (normalised) | 36 |
| cost, billed | $0.000369 |
| upstream inference cost | $0.000000 |
| records with no cost | 0 |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite-20260721 | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Per serving provider

| provider | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Google | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Per call

| generation id | model | provider | in | out | cost | latency ms | finish |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gen-1788629144-qvru4njB9kPXmnVf8O0S | google/gemini-3.5-flash-lite-20260721 | Google | 338 | 24 | $0.000161 | 928 | tool_calls |
| gen-1788629145-x0yiZwP4EgITJkubSUUh | google/gemini-3.5-flash-lite-20260721 | Google | 450 | 29 | $0.000208 | 732 | tool_calls |
