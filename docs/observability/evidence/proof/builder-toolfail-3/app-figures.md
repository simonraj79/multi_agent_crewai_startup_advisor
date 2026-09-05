# App figures - run `f0297951-e1ff-49a1-90f6-725d06d9b112`

Generated 2026-09-05T18:16:15Z from `http://127.0.0.1:8000`.
Serves the app column of DoD E1/E5 and the app half of B4.

## Run

| field | value |
| --- | --- |
| workflow_id | ug_4e7e952f |
| graph_version | c3b393e1a89362dd |
| status | failed |
| stop_reason | (none) |
| mode | run |
| started_at | 2026-09-05T18:07:35.253168Z |
| completed_at | 2026-09-05T18:07:38.938270Z |
| wall clock (s) | 3.685 |
| frames downloaded | 44 |
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
| crew | 1 | 2.413 | 2.413 |  |
| Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 1 | 2.395 | 2.395 |  |
| AgentExecutor | 1 | 2.388 | 2.388 |  |

### Tools (slowest first)

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| sounding_line_lookup | 1 | 0.015 | 0.015 |  |
| read_website_content | 1 | 0.001 | 0.001 |  |

### Nodes (slowest first)

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| chart_the_shoals | 1 | 2.699 | 2.699 |  |
| start_survey | 2 | 0.011 | 0.006 |  |
| the_brief | 1 | 0.009 | 0.009 |  |

Unclosed app-side spans: **1** (a run that is still going, or a frame pair the log does not close)
