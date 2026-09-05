# Reconciliation - run `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7`

Generated 2026-09-05T14:49:46Z by `scripts/observability/reconcile.py`.
DoD rows **E1** and **E5**. Every **Diagnosis** cell is empty on purpose:
the script measures, a verifier names the cause.

| source | what it is | file |
| --- | --- | --- |
| app | the run's own frames and snapshot | `http://127.0.0.1:8097` |
| Langfuse | session `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7`, 33 observations | public API |
| OpenRouter | 0 of 0 generation records | `GET /api/v1/generation?id=` |

## 1. Totals

| metric | app | Langfuse | OpenRouter | verdict | Diagnosis |
| --- | --- | --- | --- | --- | --- |
| calls | 6 | 6 | n/a | agree | - |
| input tokens | 3840 | 3840 | n/a | agree | - |
| output tokens | 449 | 449 | n/a | agree | - |
| total tokens | 4289 | 4289 | n/a | agree | - |
| cost (USD) | $0.002275 | $0.002275 | n/a | agree | - |

## 2. Duplicates (E1)

No generation id appears on more than one Langfuse observation. **E1 duplicate check: PASS** for this run.

## 3. Per-call join on `response_id`

- **no generation ids to join.** Not a pass: the join is the only check that can find a call present in two sources and absent from the third, and it did not run.

- app calls carrying no generation id: 6 (expected to be every call on a SYNTHETIC run - the double writes `response_id: None`)
- Langfuse generations carrying no `metadata.response_id`: 6

| generation id | model | agent_role | app in/out | LF in/out | OR in/out | app cost | LF cost | OR cost | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| - | - | - | - | - | - | - | - | - | - |

## 4. Durations, app frames versus Langfuse spans (B4)

### Per agent role

| agent_role | app spans | app total s | LF spans | LF total s | delta s | verdict | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| (none) | - | n/a | 11 | 12.023 | n/a | one side only |  |
| Community demand analyst | 1 | 2.001 | 3 | 5.996 | 3.995 | **OVER 1 s** |  |
| Market evidence analyst | 1 | 2.001 | 3 | 5.997 | 3.996 | **OVER 1 s** |  |
| Startup validation scoper | 1 | 0.002 | 3 | 0.000 | 0.002 | within 1 s |  |
| Startup validation synthesist | 1 | 0.002 | 2 | 0.000 | 0.002 | within 1 s |  |
| Technical feasibility analyst | 1 | 2.006 | 3 | 6.014 | 4.008 | **OVER 1 s** |  |
| Validation report writer | 1 | 0.007 | 2 | 0.000 | 0.007 | within 1 s |  |

### Per task name

| task_name | app spans | app total s | LF spans | LF total s | delta s | verdict | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| (none) | - | n/a | 11 | 12.023 | n/a | one side only |  |
| feasibility_task | - | n/a | 3 | 6.014 | n/a | one side only |  |
| market_task | - | n/a | 3 | 5.997 | n/a | one side only |  |
| reporting_task | - | n/a | 2 | 0.000 | n/a | one side only |  |
| scoping_task | - | n/a | 3 | 0.000 | n/a | one side only |  |
| sentiment_task | - | n/a | 3 | 5.996 | n/a | one side only |  |
| synthesis_task | - | n/a | 2 | 0.000 | n/a | one side only |  |

### Per node

| node_id | app spans | app total s | LF spans | LF total s | delta s | verdict | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| (none) | - | n/a | 1 | 6.020 | n/a | one side only |  |
| confirm_scope | 1 | 0.000 | 1 | 0.000 | 0.000 | within 1 s |  |
| persist | 1 | 0.000 | 1 | 0.000 | 0.000 | within 1 s |  |
| research_feasibility | 1 | 2.006 | 4 | 8.019 | 6.013 | **OVER 1 s** |  |
| research_market | 1 | 2.001 | 4 | 7.996 | 5.995 | **OVER 1 s** |  |
| research_sentiment | 1 | 2.001 | 4 | 7.995 | 5.994 | **OVER 1 s** |  |
| review_verdict | 1 | 0.000 | 1 | 0.000 | 0.000 | within 1 s |  |
| route_scope | 1 | 0.000 | 1 | 0.000 | 0.000 | within 1 s |  |
| route_verdict | 1 | 0.000 | 1 | 0.000 | 0.000 | within 1 s |  |
| scope_idea | 1 | 0.002 | 3 | 0.000 | 0.002 | within 1 s |  |
| synthesize | 1 | 0.002 | 3 | 0.000 | 0.002 | within 1 s |  |
| write_report | 1 | 0.007 | 3 | 0.000 | 0.007 | within 1 s |  |

### Per tool

| tool | app spans | app total s | LF spans | LF total s | delta s | verdict | Diagnosis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| analyze_community_sentiment | 1 | 2.000 | 1 | 1.998 | 0.002 | within 1 s |  |
| assess_technical_feasibility | 1 | 2.005 | 1 | 2.004 | 0.001 | within 1 s |  |
| research_market_landscape | 1 | 2.001 | 1 | 1.999 | 0.002 | within 1 s |  |

## 5. Diagnosis notes

_Verifier: one line per differing cell above. E5 accepts no cell left blank._
