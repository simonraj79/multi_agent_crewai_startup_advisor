# OpenRouter figures

Generated 2026-09-05T18:17:43Z. DoD E1 / E5, OpenRouter column.

Token counts here are OpenRouter's **native** counts; `tokens_prompt` /
`tokens_completion` are its normalised (GPT-tokeniser) figures and are
reported separately, because comparing a native count against the app's
provider-reported count is the like-for-like comparison and the
normalised one is not.

| metric | value |
| --- | --- |
| ids requested | 11 |
| records found | 11 |
| NOT found | 0 |
| input tokens (native) | 37379 |
| output tokens (native) | 8678 |
| total tokens (native) | 46057 |
| input tokens (normalised) | 35325 |
| output tokens (normalised) | 7930 |
| cost, billed | $0.056977 |
| upstream inference cost | $0.000000 |
| records with no cost | 0 |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite-20260721 | 6 | 13460 | 1464 | 14924 | $0.011985 |  |
| google/gemini-3.8-flash-20260902 | 5 | 23919 | 7214 | 31133 | $0.044992 |  |
| **SUM** | 11 | 37379 | 8678 | 46057 | $0.056977 |  |

## Per serving provider

| provider | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Google | 8 | 30682 | 8546 | 39228 | $0.054638 |  |
| Google AI Studio | 3 | 6697 | 132 | 6829 | $0.002339 |  |
| **SUM** | 11 | 37379 | 8678 | 46057 | $0.056977 |  |

## Per call

| generation id | model | provider | in | out | cost | latency ms | finish |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gen-1788631659-U9FowbvkAWavoSe0nql5 | google/gemini-3.8-flash-20260902 | Google | 1698 | 1188 | $0.005729 | 1834 | stop |
| gen-1788631669-5QuoC6M2UMAGWES2rr8s | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 1952 | 36 | $0.000676 | 645 | tool_calls |
| gen-1788631669-oJyryMHtWvx5vCblKbvm | google/gemini-3.5-flash-lite-20260721 | Google | 1669 | 25 | $0.001014 | 870 | tool_calls |
| gen-1788631671-oc87DXpA59GvxP8NxtDU | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2080 | 68 | $0.000794 | 579 | stop |
| gen-1788631671-Yhp5eTIYrHgMCanh4JNr | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2665 | 28 | $0.000870 | 516 | tool_calls |
| gen-1788631674-AM2MaLzT0eXnJD7VEjPF | google/gemini-3.5-flash-lite-20260721 | Google | 2067 | 631 | $0.003956 | 938 | stop |
| gen-1788631678-0oDPMAnfDwOD32an9Aw2 | google/gemini-3.5-flash-lite-20260721 | Google | 3027 | 676 | $0.004677 | 982 | stop |
| gen-1788631684-8vd5f93wrLkkCvAAu0XQ | google/gemini-3.8-flash-20260902 | Google | 7938 | 583 | $0.008140 | 4851 | stop |
| gen-1788631690-2AKrctJTxsN1BwrI6iWo | google/gemini-3.8-flash-20260902 | Google | 4320 | 2847 | $0.013916 | 14240 | stop |
| gen-1788631704-s8AccU7wZfIptPVq4C3V | google/gemini-3.8-flash-20260902 | Google | 6963 | 2586 | $0.014920 | 12587 | stop |
| gen-1788631717-S88c2kn0Sns6KVr8PyxF | google/gemini-3.8-flash-20260902 | Google | 3000 | 10 | $0.002288 | 1399 | stop |
