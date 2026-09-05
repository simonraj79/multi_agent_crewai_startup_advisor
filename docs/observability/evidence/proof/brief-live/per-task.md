# Per task_name - run `6586c854-3ca3-44c4-a587-eb6a3ef01962`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| analysis_task | 1 | 1916 | 2552 | 4468 | $0.011007 |  |
| research_task | 5 | 87195 | 1427 | 88622 | $0.029726 |  |
| writing_task | 4 | 7676 | 13627 | 21303 | $0.056858 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.097591 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 10 | 96787 | 17606 | 114393 | $0.097591 | - |
| every GENERATION in the trace | 10 | 96787 | 17606 | 114393 | $0.097591 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 10 |  |  | 114393 | $0.097591 | **YES** |
| the APP's own frame-derived total | 10 | 96787 | 17606 | 114393 | $0.097591 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
