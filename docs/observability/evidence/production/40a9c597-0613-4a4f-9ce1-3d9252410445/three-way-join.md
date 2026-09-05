# Three-way join - run `40a9c597-0613-4a4f-9ce1-3d9252410445`

Written BY HAND (an ad-hoc join over the three pulled JSON files), because
`reconcile.py --app` is required and exits 2 without an `app-figures.json`,
and the app side of this run is unreachable - see `app-side-probe.json`.
The app column below is the trace's own `metadata.run_metrics`
(`source: app-snapshot`, `reason: run_completed`), not a `pull_app_run.py` pull.
The estimate column re-runs `brief_crew.config.compute_cost_usd` - the app's own
pricing function - over the Langfuse token counts.

| # | generation id | model | task | att | LF in/out | OR in/out | LF cost | OR cost | app PRICES est | Δ est→billed |
| ---: | --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | `gen-1788647590-ahTnRnBz4ohNZih5Vx0s` | google/gemini-3.8-flash | scoping_task | 1 | 1673/785 | 1673/785 (same) | $0.004198 | $0.004198 | $0.004198 | +0.0% |
| 2 | `gen-1788647596-y0DwNOWxW9DRy7HL2gtf` | google/gemini-3.5-flash-lite:nitro | sentiment_task | 1 | 1935/36 | 1935/36 (same) | $0.001207 | $0.001207 | $0.000670 | +80.0% |
| 3 | `gen-1788647596-aFmJkSi7DIhwmfvJ53nG` | google/gemini-3.5-flash-lite:nitro | feasibility_task | 1 | 1697/26 | 1697/26 (same) | $0.001033 | $0.001033 | $0.000574 | +80.0% |
| 4 | `gen-1788647599-tsL8k30LxCNI1i0m912l` | google/gemini-3.5-flash-lite:nitro | market_task | 1 | 2650/31 | 2650/31 (same) | $0.001571 | $0.001571 | $0.000873 | +80.0% |
| 5 | `gen-1788647600-OTr3Vf0yZbDJLLXDvi2H` | google/gemini-3.5-flash-lite:nitro | feasibility_task | 2 | 2314/538 | 2314/538 (same) | $0.003671 | $0.003671 | $0.002039 | +80.0% |
| 6 | `gen-1788647601-R5Q3YaI2qXUueEziha7z` | google/gemini-3.5-flash-lite:nitro | sentiment_task | 2 | 2819/819 | 2819/819 (same) | $0.005208 | $0.005208 | $0.002893 | +80.0% |
| 7 | `gen-1788647605-HrXlEWF1Zs2hISu8gsvA` | google/gemini-3.5-flash-lite:nitro | market_task | 2 | 3270/715 | 3270/715 (same) | $0.004983 | $0.004983 | $0.002769 | +80.0% |
| 8 | `gen-1788647607-WxNQsm5CDfk6B44C4u3a` | google/gemini-3.5-flash-lite:nitro | market_task | 3 | 3719/720 | 3719/720 (same) | $0.005248 | $0.005248 | $0.002916 | +80.0% |
| 9 | `gen-1788647611-eMefnnzy6edsQAsWeKrz` | google/gemini-3.8-flash | synthesis_task | 1 | 7347/837 | 7347/837 (same) | $0.008649 | $0.008649 | $0.008649 | +0.0% |
| 10 | `gen-1788647615-ig5UcJAIYrBwxSB9Au2V` | google/gemini-3.8-flash | reporting_task | 1 | 5099/3295 | 5099/3295 (same) | $0.016181 | $0.016181 | $0.016181 | +0.0% |
| 11 | `gen-1788647623-6jT1Z3rkocp6kiYJUfL2` | google/gemini-3.8-flash | reporting_task | 2 | 8197/3309 | 8197/3309 (same) | $0.018557 | $0.018557 | $0.018557 | +0.0% |
| 12 | `gen-1788647630-BkVBwDTVGLDlMYCGTR1K` | google/gemini-3.8-flash | reporting_task | 3 | 8188/3013 | 8188/3013 (same) | $0.017440 | $0.017440 | $0.017440 | +0.0% |
| | **SUM** | | | | 48908/14124 | | **$0.087945** | **$0.087945** | **$0.077758** | +13.1% |

run_metrics.usage: {"successful_requests": 12, "prompt_tokens": 48908, "completion_tokens": 14124, "total_tokens": 63032, "call_count": 12, "elapsed_ms": 42454, "cost_usd": 0.07775795}
LF totals: 48908 14124 63032 0.08794491
diff lf costDetails vs OR total_cost, per call: 0
cost_source values: ['openrouter-billed']
providers: ['Google', 'Google AI Studio']
levels: ['DEFAULT']
finish reasons: ['stop', 'tool_calls']
distinct fingerprints: 12 of 12 basis: ['messages']
sum generation duration ms: 42302
app elapsed_ms: 42454
