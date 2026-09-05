# OpenRouter figures

Generated 2026-09-05T22:41:46Z. DoD E1 / E5, OpenRouter column.

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
| input tokens (native) | 48908 |
| output tokens (native) | 14124 |
| total tokens (native) | 63032 |
| input tokens (normalised) | 44871 |
| output tokens (normalised) | 11705 |
| cost, billed | $0.087945 |
| upstream inference cost | $0.000000 |
| records with no cost | 0 |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite-20260721 | 7 | 18404 | 2885 | 21289 | $0.022921 |  |
| google/gemini-3.8-flash-20260902 | 5 | 30504 | 11239 | 41743 | $0.065024 |  |
| **SUM** | 12 | 48908 | 14124 | 63032 | $0.087945 |  |

## Per serving provider

| provider | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Google | 1 | 1673 | 785 | 2458 | $0.004198 |  |
| Google AI Studio | 11 | 47235 | 13339 | 60574 | $0.083746 |  |
| **SUM** | 12 | 48908 | 14124 | 63032 | $0.087945 |  |

## Per call

| generation id | model | provider | in | out | cost | latency ms | finish |
| --- | --- | --- | --- | --- | --- | --- | --- |
| gen-1788647630-BkVBwDTVGLDlMYCGTR1K | google/gemini-3.8-flash-20260902 | Google AI Studio | 8188 | 3013 | $0.017440 | 6745 | stop |
| gen-1788647623-6jT1Z3rkocp6kiYJUfL2 | google/gemini-3.8-flash-20260902 | Google AI Studio | 8197 | 3309 | $0.018557 | 7020 | stop |
| gen-1788647615-ig5UcJAIYrBwxSB9Au2V | google/gemini-3.8-flash-20260902 | Google AI Studio | 5099 | 3295 | $0.016181 | 7523 | stop |
| gen-1788647611-eMefnnzy6edsQAsWeKrz | google/gemini-3.8-flash-20260902 | Google AI Studio | 7347 | 837 | $0.008649 | 3103 | stop |
| gen-1788647607-WxNQsm5CDfk6B44C4u3a | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 3719 | 720 | $0.005248 | 555 | stop |
| gen-1788647605-HrXlEWF1Zs2hISu8gsvA | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 3270 | 715 | $0.004983 | 540 | stop |
| gen-1788647601-R5Q3YaI2qXUueEziha7z | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2819 | 819 | $0.005208 | 578 | stop |
| gen-1788647600-OTr3Vf0yZbDJLLXDvi2H | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2314 | 538 | $0.003671 | 605 | stop |
| gen-1788647599-tsL8k30LxCNI1i0m912l | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 2650 | 31 | $0.001571 | 617 | tool_calls |
| gen-1788647596-aFmJkSi7DIhwmfvJ53nG | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 1697 | 26 | $0.001033 | 576 | tool_calls |
| gen-1788647596-y0DwNOWxW9DRy7HL2gtf | google/gemini-3.5-flash-lite-20260721 | Google AI Studio | 1935 | 36 | $0.001207 | 535 | tool_calls |
| gen-1788647590-ahTnRnBz4ohNZih5Vx0s | google/gemini-3.8-flash-20260902 | Google | 1673 | 785 | $0.004198 | 1904 | stop |
