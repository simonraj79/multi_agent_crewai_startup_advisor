# Durations - run `4548c884-6e5c-404c-a28a-bbf5a8ce8cf7`

DoD B4: Langfuse spans against the app's own frame timestamps.
Generated 2026-09-05T14:49:46Z. Tolerance in the verdict column: 1 s.

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
