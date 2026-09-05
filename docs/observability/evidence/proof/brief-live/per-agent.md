# Per agent_role - run `6586c854-3ca3-44c4-a587-eb6a3ef01962`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 2 | 4592 | 8655 | 13247 | $0.035900 |  |
| Guardrail Agent | 2 | 3084 | 4972 | 8056 | $0.020958 |  |
| Senior Research Analyst specialising in predictive maintenance for commercial building lifts | 5 | 87195 | 1427 | 88622 | $0.029726 |  |
| Strategy Analyst turning raw research on predictive maintenance for commercial building lifts into a defensible point of view | 1 | 1916 | 2552 | 4468 | $0.011007 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.097591 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 10 | 96787 | 17606 | 114393 | $0.097591 | - |
| every GENERATION in the trace | 10 | 96787 | 17606 | 114393 | $0.097591 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 10 |  |  | 114393 | $0.097591 | **YES** |
| the APP's own frame-derived total | 10 | 96787 | 17606 | 114393 | $0.097591 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
