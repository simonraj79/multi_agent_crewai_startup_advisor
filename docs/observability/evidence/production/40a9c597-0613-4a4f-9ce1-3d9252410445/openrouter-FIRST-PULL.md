# OpenRouter figures

Generated 2026-09-05T22:37:15Z. DoD E1 / E5, OpenRouter column.

Token counts here are OpenRouter's **native** counts; `tokens_prompt` /
`tokens_completion` are its normalised (GPT-tokeniser) figures and are
reported separately, because comparing a native count against the app's
provider-reported count is the like-for-like comparison and the
normalised one is not.

| metric | value |
| --- | --- |
| ids requested | 6 |
| records found | 6 |
| NOT found | 0 |
| input tokens (native) | 35820 |
| output tokens (native) | 11889 |
| total tokens (native) | 47709 |
| input tokens (normalised) | 31838 |
| output tokens (normalised) | 9984 |
| cost, billed | $0.071057 |
| upstream inference cost | $0.000000 |
| records with no cost | 0 |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite-20260721 | 2 | 6989 | 1435 | 8424 | $0.010232 |  |
| google/gemini-3.8-flash-20260902 | 4 | 28831 | 10454 | 39285 | $0.060826 |  |
| **SUM** | 6 | 35820 | 11889 | 47709 | $0.071057 |  |

## Per serving provider

| provider | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Google AI Studio | 6 | 35820 | 11889 | 47709 | $0.071057 |  |
| **SUM** | 6 | 35820 | 11889 | 47709 | $0.071057 |  |

## Per call

| generation id | model | provider | in | out | cost | latency ms | finish |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gen-1788647630-BkVBwDTVGLDlMYCGTR1K | google/gemini-3.8-flash-20260902 | Google AI Studio | 8188 | 3013 | $0.017440 | 6745 | stop |
| gen-1788647623-6jT1Z3rkocp6kiYJUfL2 | google/gemini-3.8-flash-20260902 | Google AI Studio | 8197 | 3309 | $0.018557 | 7020 | stop |
| gen-1788647615-ig5UcJAIYrBwxSB9Au2V | google/gemini-3.8-flash-20260902 | Google AI Studio | 5099 | 3295 | $0.016181 | 7523 | stop |
| gen-1788647611-eMefnnzy6edsQAsWeKrz | google/gemini-3.8-flash-20260902 | Google AI Studio | 7347 | 837 | $0.008649 | 3103 | stop |
| gen-1788647607-WxNQsm5CDfk6B44C4u3a | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 3719 | 720 | $0.005248 | 555 | stop |
| gen-1788647605-HrXlEWF1Zs2hISu8gsvA | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 3270 | 715 | $0.004983 | 540 | stop |
