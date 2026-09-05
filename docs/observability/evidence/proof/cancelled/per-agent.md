# Per agent_role - run `073c021f-4ff7-43e1-84d5-d9e8dd7fa0ba`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 96 | 736 | $0.000432 |  |
| Market evidence analyst | 1 | 640 | 96 | 736 | $0.000432 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 95 | 735 | $0.000429 |  |
| Technical feasibility analyst | 1 | 640 | 97 | 737 | $0.000434 |  |
| **SUM** | 5 | 3200 | 452 | 3652 | $0.002090 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 5 | 3200 | 452 | 3652 | $0.002090 | - |
| every GENERATION in the trace | 5 | 3200 | 452 | 3652 | $0.002090 | **YES** |
| trace metadata `run_metrics` (reason: run_cancelled) | 5 |  |  | 3652 | $0.002090 | **YES** |
| the APP's own frame-derived total | 5 | 3200 | 452 | 3652 | $0.002090 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
