# Per task_name - run `1a0bea14-ffb3-459d-b5fc-f714a76e5f71`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 2 | 4147 | 581 | 4728 | $0.004854 |  |
| market_task | 3 | 9423 | 1252 | 10675 | $0.010722 |  |
| reporting_task | 3 | 14728 | 5804 | 20532 | $0.032811 |  |
| scoping_task | 1 | 1698 | 880 | 2578 | $0.004574 |  |
| sentiment_task | 2 | 4142 | 123 | 4265 | $0.002790 |  |
| synthesis_task | 1 | 8056 | 700 | 8756 | $0.008667 |  |
| **SUM** | 12 | 42194 | 9340 | 51534 | $0.064418 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 12 | 42194 | 9340 | 51534 | $0.064418 | - |
| every GENERATION in the trace | 12 | 42194 | 9340 | 51534 | $0.064418 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 12 |  |  | 51534 | $0.056255 | **YES** |
| the APP's own frame-derived total | 12 | 42194 | 9340 | 51534 | $0.056255 | **YES** |

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role` | 12 | 0 | 0 |  |
| `task_name`  <- this table groups on it | 11 | 1 | 0 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
