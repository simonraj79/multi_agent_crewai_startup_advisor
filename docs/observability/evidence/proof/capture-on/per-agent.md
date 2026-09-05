# Per agent_role - run `c5d1dde9-c22d-4621-a171-9a7e85803105`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 123 | 763 | $0.000500 |  |
| Market evidence analyst | 1 | 640 | 123 | 763 | $0.000500 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 122 | 762 | $0.000497 |  |
| Technical feasibility analyst | 1 | 640 | 124 | 764 | $0.000502 |  |
| Validation report writer | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 628 | 4468 | $0.002722 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 6 | 3840 | 628 | 4468 | $0.002722 | - |
| every GENERATION in the trace | 6 | 3840 | 628 | 4468 | $0.002722 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 6 |  |  | 4468 | $0.002722 | **YES** |
| the APP's own frame-derived total | 6 | 3840 | 628 | 4468 | $0.002722 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
