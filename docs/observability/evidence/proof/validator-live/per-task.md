# Per task_name - run `f4c8c779-52f2-40e1-9351-2668ea276ae4`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 2 | 4116 | 574 | 4690 | $0.002670 |  |
| market_task | 2 | 5924 | 623 | 6547 | $0.003335 |  |
| reporting_task | 2 | 7543 | 2752 | 10295 | $0.015977 |  |
| scoping_task | 1 | 1698 | 1417 | 3115 | $0.006587 |  |
| sentiment_task | 2 | 4100 | 127 | 4227 | $0.001548 |  |
| synthesis_task | 1 | 6435 | 878 | 7313 | $0.008119 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 10 | 29816 | 6371 | 36187 | $0.038235 | - |
| every GENERATION in the trace | 10 | 29816 | 6371 | 36187 | $0.038235 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 10 |  |  | 36187 | $0.038235 | **YES** |
| the APP's own frame-derived total | 10 | 29816 | 6371 | 36187 | $0.038235 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
