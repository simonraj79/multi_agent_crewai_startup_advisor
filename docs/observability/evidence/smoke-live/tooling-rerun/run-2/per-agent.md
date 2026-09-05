# Per agent_role - run `036ace4e-8b58-4a9b-9d46-0b78448684f9`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 1 | 640 | 76 | 716 | $0.000382 |  |
| Market evidence analyst | 1 | 640 | 75 | 715 | $0.000380 |  |
| Startup validation scoper | 1 | 640 | 68 | 708 | $0.000362 |  |
| Startup validation synthesist | 1 | 640 | 74 | 714 | $0.000377 |  |
| Technical feasibility analyst | 1 | 640 | 76 | 716 | $0.000382 |  |
| Validation report writer | 1 | 640 | 68 | 708 | $0.000362 |  |
| **SUM** | 6 | 3840 | 437 | 4277 | $0.002244 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 6 | 3840 | 437 | 4277 | $0.002244 | - |
| every GENERATION in the trace | 6 | 3840 | 437 | 4277 | $0.002244 | **YES** |
| the APP's own frame-derived total | 6 | 3840 | 437 | 4277 | $0.002244 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
