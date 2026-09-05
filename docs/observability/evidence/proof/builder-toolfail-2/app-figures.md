# App figures - run `6342e33f-268e-4b67-87ae-1574a2fffbeb`

Generated 2026-09-05T17:26:10Z from `http://127.0.0.1:8000`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | ug_4e7e952f |
| graph_version | c3b393e1a89362dd |
| status | failed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T17:25:40.871118Z |
| completed_at | 2026-09-05T17:25:43.236579Z |
| wall clock (s) | 2.365 |
| frames downloaded | 43 |
| error | Tool 'read_website_content' failed during 'Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRST call sounding_line_lookup with water set to the stretch of water named above - that is the survey office depth register. THEN call your website-reading tool with website_url set to https://sounding-line.invalid/shoals, which is the register's shoal appendix. Then report what EACH of the two tools returned, naming the tool in each case.': Could not resolve hostname: 'sounding-line.invalid' (code: ValueError) |

## Totals, from the TOKEN frames

| metric | value |
| --- | --- |
| LLM calls | 2 |
| input tokens | 788 |
| output tokens | 53 |
| total tokens | 841 |
| cost (app estimate) | $0.000369 |
| calls with no price on file | 0 |
| failed LLM calls (no tokens) | 0 |
| tool calls (finished or errored) | 2 |
| generation ids captured | 2 |
| calls with no generation id | 0 |

## Frames versus the app's own snapshot

| metric | from frames | from GET /api/runs/{id} | agree |
| --- | --- | --- | --- |
| calls | 2 | 2 | yes |
| input_tokens | 788 | 788 | yes |
| output_tokens | 53 | 53 | yes |
| total_tokens | 841 | 841 | yes |
| cost_usd | 0.00036889999999999997 | 0.0003689 | yes |

## Per agent role

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Tidewater Cartographer | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Per task name

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Per node

| node_id | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| chart_the_shoals | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Per model

| model | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| google/gemini-3.5-flash-lite | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Durations, from frame timestamps

### Agents (slowest first)

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Tidewater Cartographer | 1 | 0.000 | 0.000 | 1 |

### Tasks (slowest first)

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| crew | 1 | 2.018 | 2.018 |  |
| Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 1 | 2.004 | 2.004 |  |
| AgentExecutor | 1 | 1.996 | 1.996 |  |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sounding_line_lookup | 1 | 0.012 | 0.012 |  |
| read_website_content | 1 | 0.000 | 0.000 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| chart_the_shoals | 1 | 2.338 | 2.338 |  |
| start_survey | 2 | 0.007 | 0.004 |  |
| the_brief | 1 | 0.004 | 0.004 |  |

Unclosed app-side spans: **1** (a run that is still going, or a frame pair the log does not close)
