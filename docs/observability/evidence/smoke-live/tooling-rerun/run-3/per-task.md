# Per task_name - run `9d356fcb-aadd-4d41-ab06-7ffcd50c78ea`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 1 | 640 | 77 | 717 | $0.000385 |  |
| market_task | 1 | 640 | 76 | 716 | $0.000382 |  |
| reporting_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| scoping_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| sentiment_task | 1 | 640 | 77 | 717 | $0.000385 |  |
| synthesis_task | 1 | 640 | 75 | 715 | $0.000380 |  |
| **SUM** | 6 | 3840 | 441 | 4281 | $0.002254 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 6 | 3840 | 441 | 4281 | $0.002254 | - |
| every GENERATION in the trace | 6 | 3840 | 441 | 4281 | $0.002254 | **YES** |
| the APP's own frame-derived total | 6 | 3840 | 441 | 4281 | $0.002255 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
