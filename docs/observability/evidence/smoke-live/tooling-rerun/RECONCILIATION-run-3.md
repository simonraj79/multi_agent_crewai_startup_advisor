# Reconciliation - run `9d356fcb-aadd-4d41-ab06-7ffcd50c78ea`

Generated 2026-09-05T15:19:14Z by `scripts/observability/reconcile.py`.
DoD rows **E1** and **E5**. Every **Diagnosis** cell is empty on purpose:
the script measures, a verifier names the cause.

| source | what it is | file |
| --- | --- | --- |
| app | the run's own frames and snapshot | `docs\observability\evidence\smoke-live\run-3\app-run.json (offline)` |
| Langfuse | session `9d356fcb-aadd-4d41-ab06-7ffcd50c78ea`, 33 observations | public API |
| OpenRouter | 0 of 0 generation records | `GET /api/v1/generation?id=` |

## 1. Totals

| metric | app | Langfuse | OpenRouter | verdict | Diagnosis |
| --- | --- | --- | --- | --- | --- |
| calls | 6 | 6 | n/a | agree | - |
| input tokens | 3840 | 3840 | n/a | agree | - |
| output tokens | 441 | 441 | n/a | agree | - |
| total tokens | 4281 | 4281 | n/a | agree | - |
| cost (USD) | $0.002255 | $0.002254 | n/a | agree | - |

## 2. E1 - nothing reaches Langfuse twice

### 2a. GENERATION observations against the app's LLM calls

| measurement | value |
| --- | --- |
| GENERATION observations in the session | 6 |
| LLM after-frames the app recorded | 6 |
| app calls that FAILED (an ERROR generation, no tokens) | 0 |
| verdict | PASS |

one GENERATION observation per LLM call: no second copy inside the session.

### 2b. A generation id carried by two Langfuse observations

No generation id appears on more than one Langfuse observation. **E1 duplicate check: PASS** for this run.

### 2c. A SECOND trace in the same window, from OpenRouter's broadcast

| measurement | value |
| --- | --- |
| window scanned | 2026-09-05T14:36:11.421000Z .. 2026-09-05T14:56:17.440000Z (+/-10 min) |
| traces in the window | 3 |
| this run's own traces, excluded | 1 |
| OTHER traces carrying `openrouter.api_key_name` | 0 |
| verdict | PASS |

No second trace carries the OpenRouter broadcast's own metadata key in this window, so this run was reported once.

## 3. Per-call join on `response_id`

- **no generation ids to join.** Not a pass: the join is the only check that can find a call present in two sources and absent from the third, and it did not run.

- app calls carrying no generation id: 6 (expected to be every call on a SYNTHETIC run - the double writes `response_id: None`)
- Langfuse generations carrying no `metadata.response_id`: 6

| generation id | model | agent_role | app in/out | LF in/out | OR in/out | app cost | LF cost | OR cost | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| - | - | - | - | - | - | - | - | - | - |

## 4. Durations, app frames versus Langfuse spans (B4)

Every row is ONE observation against ONE app span, matched on role, label and start order. A child's duration is never added to its parent's: the contract nests node -> task -> agent -> tool over one call, and summing that tree turns a 2.006 s agent into 6.014 s.

Slowest first, which is the ranking B4 asks for.

#### The B4 answer

| the slowest | label | Langfuse s | app s |
| --- | --- | --- | --- |
| agent | Technical feasibility analyst | 2.011 | 2.012 |
| task | feasibility_task | 2.011 | n/a |
| tool | assess_technical_feasibility | 2.010 | 2.011 |

Rows outside the 1 s tolerance: **0**.

### Agents - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Technical feasibility analyst | 1 | 2.012 | 2.011 | 0.001 | within 1 s | 984acb2a3ad716a9 |  |
| 2 | Market evidence analyst | 1 | 2.002 | 2.000 | 0.002 | within 1 s | 3a43fe40d03d5c13 |  |
| 3 | Community demand analyst | 1 | 2.001 | 2.000 | 0.001 | within 1 s | f6601de8db41d015 |  |
| 4 | Startup validation scoper | 1 | 0.000 | 0.000 | 0.000 | within 1 s | e76badd421b3c57b |  |
| 5 | Startup validation synthesist | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 803c407fb80109a8 |  |
| 6 | Validation report writer | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 3b7d65d51c1cdb99 |  |

### Tasks - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | feasibility_task | 1 | n/a | 2.011 | n/a | Langfuse only | e264ef1a642917b8 |  |
| 2 | market_task | 1 | n/a | 2.000 | n/a | Langfuse only | cd69ad9c5b62339f |  |
| 3 | sentiment_task | 1 | n/a | 2.000 | n/a | Langfuse only | 3aa826d29418e5b4 |  |
| 4 | reporting_task | 1 | n/a | 0.000 | n/a | Langfuse only | 5204bd15d590a845 |  |
| 5 | scoping_task | 1 | n/a | 0.000 | n/a | Langfuse only | 65b213a5430aed24 |  |
| 6 | synthesis_task | 1 | n/a | 0.000 | n/a | Langfuse only | 869d1f4c2ea0c791 |  |

### Tools - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | assess_technical_feasibility | 1 | 2.011 | 2.010 | 0.001 | within 1 s | d0c49dcc6da23f6c |  |
| 2 | research_market_landscape | 1 | 2.002 | 2.000 | 0.002 | within 1 s | 9b60c97ced694ae9 |  |
| 3 | analyze_community_sentiment | 1 | 2.000 | 1.999 | 0.001 | within 1 s | 86928232a1c47d12 |  |

### Nodes - one row per observation

| rank | label | # | app s | Langfuse s | delta s | verdict | observation id | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | research_feasibility | 1 | 2.012 | 2.011 | 0.001 | within 1 s | 59ee61bed8bd97db |  |
| 2 | research_market | 1 | 2.002 | 2.000 | 0.002 | within 1 s | 8d3c80066ed856b0 |  |
| 3 | research_sentiment | 1 | 2.002 | 2.001 | 0.001 | within 1 s | 2b0838a1f9f658f2 |  |
| 4 | write_report | 1 | 0.001 | 0.000 | 0.001 | within 1 s | 353d7ebd191e0d41 |  |
| 5 | confirm_scope | 1 | 0.000 | 0.000 | 0.000 | within 1 s | ab7ee24395f2b2ba |  |
| 6 | persist | 1 | 0.000 | 0.000 | 0.000 | within 1 s | ffd83b6f93573bfc |  |
| 7 | review_verdict | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 508da1133742fff7 |  |
| 8 | route_scope | 1 | 0.000 | 0.000 | 0.000 | within 1 s | f84531f6cb0c92f7 |  |
| 9 | route_verdict | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 4f4647209e5e89a3 |  |
| 10 | scope_idea | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 902f0e251961881a |  |
| 11 | synthesize | 1 | 0.000 | 0.000 | 0.000 | within 1 s | 9e18fe5ab339a821 |  |

Langfuse observations paired: 33 available.

## 5. Diagnosis notes

_Verifier: one line per differing cell above. E5 accepts no cell left blank._
