# OpenRouter figures

Generated 2026-09-05T16:40:43Z. DoD E1 / E5, OpenRouter column.

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
| input tokens (native) | 96787 |
| output tokens (native) | 17606 |
| total tokens (native) | 114393 |
| input tokens (normalised) | 96627 |
| output tokens (normalised) | 9702 |
| cost, billed | $0.088761 |
| upstream inference cost | $0.000000 |
| records with no cost | 0 |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite-20260721 | 5 | 87195 | 1427 | 88622 | $0.020896 |  |
| google/gemini-3.8-flash-20260902 | 5 | 9592 | 16179 | 25771 | $0.067865 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.088761 |  |

## Per serving provider

| provider | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Google | 5 | 9592 | 16179 | 25771 | $0.067865 |  |
| Google AI Studio | 5 | 87195 | 1427 | 88622 | $0.020896 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.088761 |  |

## Per call

| generation id | model | provider | in | out | cost | latency ms | finish |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gen-1788626088-llGgVaOxTWDAq063vgUM | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 880 | 39 | $0.000362 | 674 | tool_calls |
| gen-1788626090-5vRjFbAf9cpScL0N35EW | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2930 | 43 | $0.000986 | 716 | tool_calls |
| gen-1788626093-VVxaWEKA2sDV7GgFoy03 | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 17313 | 40 | $0.005294 | 778 | tool_calls |
| gen-1788626097-Z8k47gHvmpCj2WCRmwdc | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 27912 | 43 | $0.004067 | 796 | tool_calls |
| gen-1788626101-iF3QXjmImQTlNsVhil5o | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 38160 | 1262 | $0.010187 | 847 | stop |
| gen-1788626105-t7w03UySvbOvvuvRGJUV | google/gemini-3.8-flash-20260902 | Google | 1916 | 2552 | $0.011007 | 2841 | stop |
| gen-1788626129-nscdqWJZwFK7PyalekA8 | google/gemini-3.8-flash-20260902 | Google | 2592 | 4391 | $0.018410 | 2420 | stop |
| gen-1788626158-FrBDW35Lw5qdRYxHbYyk | google/gemini-3.8-flash-20260902 | Google | 1522 | 2399 | $0.010138 | 2336 | stop |
| gen-1788626177-DdVfMYNU9ra4nUmnbo4P | google/gemini-3.8-flash-20260902 | Google | 2000 | 4264 | $0.017490 | 1971 | stop |
| gen-1788626200-h9JBqTkNVI3HPKEkGxvw | google/gemini-3.8-flash-20260902 | Google | 1562 | 2573 | $0.010820 | 1932 | stop |
