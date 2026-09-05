# Per task_name - run `036ace4e-8b58-4a9b-9d46-0b78448684f9`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 1 | 640 | 76 | 716 | $0.000382 |  |
| market_task | 1 | 640 | 75 | 715 | $0.000380 |  |
| reporting_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| scoping_task | 1 | 640 | 68 | 708 | $0.000362 |  |
| sentiment_task | 1 | 640 | 76 | 716 | $0.000382 |  |
| synthesis_task | 1 | 640 | 74 | 714 | $0.000377 |  |
| **SUM** | 6 | 3840 | 437 | 4277 | $0.002244 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 6 | 3840 | 437 | 4277 | $0.002244 | - |
| every GENERATION in the trace | 6 | 3840 | 437 | 4277 | $0.002244 | **YES** |
| the APP's own frame-derived total | 6 | 3840 | 437 | 4277 | $0.002244 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
