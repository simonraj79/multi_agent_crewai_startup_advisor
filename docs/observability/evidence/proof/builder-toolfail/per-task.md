# Per task_name - run `9becf713-e984-45a9-b9c0-5b229a15cb60`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Take a sounding for the Tidewater approaches, north channel. You MUST call BOTH of your tools, in this order and once each. FIRS | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 2 | 788 | 53 | 841 | $0.000369 | - |
| every GENERATION in the trace | 2 | 788 | 53 | 841 | $0.000369 | **YES** |
| trace metadata `run_metrics` (reason: run_failed) | 2 |  |  | 841 | $0.000369 | **YES** |
| the APP's own frame-derived total | 2 | 788 | 53 | 841 | $0.000369 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
