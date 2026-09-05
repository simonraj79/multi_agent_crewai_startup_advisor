# App figures - run `6586c854-3ca3-44c4-a587-eb6a3ef01962`

Generated 2026-09-05T16:40:15Z from `http://127.0.0.1:8000`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | brief-flow |
| graph_version | 078969f5584a51e0 |
| status | completed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T16:34:41.582014Z |
| completed_at | 2026-09-05T16:36:58.862945Z |
| wall clock (s) | 137.281 |
| frames downloaded | 116 |
| error | (none) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 10 |
| input tokens | 96787 |
| output tokens | 17606 |
| total tokens | 114393 |
| cost (app estimate) | $0.097591 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 0 |
| tool calls (finished or errored) | 4 |
| generation ids captured | 10 |
| calls with no generation id | 0 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 10 | 10 | yes |
| input_tokens | 96787 | 96787 | yes |
| output_tokens | 17606 | 17606 | yes |
| total_tokens | 114393 | 114393 | yes |
| cost_usd | 0.09759125000000002 | 0.09759125 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 2 | 4592 | 8655 | 13247 | $0.035900 |  |
| Guardrail Agent | 2 | 3084 | 4972 | 8056 | $0.020958 |  |
| Senior Research Analyst specialising in predictive maintenance for commercial building lifts | 5 | 87195 | 1427 | 88622 | $0.029726 |  |
| Strategy Analyst turning raw research on predictive maintenance for commercial building lifts into a defensible point of view | 1 | 1916 | 2552 | 4468 | $0.011007 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.097591 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | 2 | 3084 | 4972 | 8056 | $0.020958 |  |
| analysis_task | 1 | 1916 | 2552 | 4468 | $0.011007 |  |
| research_task | 5 | 87195 | 1427 | 88622 | $0.029726 |  |
| writing_task | 2 | 4592 | 8655 | 13247 | $0.035900 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.097591 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| scrape_web | 10 | 96787 | 17606 | 114393 | $0.097591 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.097591 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite:nitro | 5 | 87195 | 1427 | 88622 | $0.029726 |  |
| google/gemini-3.8-flash | 5 | 9592 | 16179 | 25771 | $0.067865 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.097591 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 2 | 52.758 | 29.093 |  |
| Strategy Analyst turning raw research on predictive maintenance for commercial building lifts into a defensible point of view | 1 | 23.882 | 23.882 |  |
| Senior Research Analyst specialising in predictive maintenance for commercial building lifts | 1 | 17.584 | 17.584 |  |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| BriefCrew | 1 | 130.248 | 130.248 |  |
| AgentExecutor | 6 | 130.143 | 29.088 |  |
| writing_task | 1 | 88.726 | 88.726 |  |
| analysis_task | 1 | 23.887 | 23.887 |  |
| research_task | 1 | 17.587 | 17.587 |  |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| firecrawl_web_scrape_tool | 3 | 7.655 | 3.166 |  |
| firecrawl_web_search_tool | 1 | 1.779 | 1.779 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| scrape_web | 1 | 131.062 | 131.062 |  |
| index_content | 1 | 3.351 | 3.351 |  |
| retrieve_cached | 1 | 2.843 | 2.843 |  |
| check_cache | 1 | 0.003 | 0.003 |  |
| persist | 1 | 0.003 | 0.003 |  |
| write_brief | 1 | 0.002 | 0.002 |  |

Unclosed app-side spans: **0**
