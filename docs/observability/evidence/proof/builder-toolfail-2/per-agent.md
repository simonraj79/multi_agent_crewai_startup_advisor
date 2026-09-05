# Per agent_role - run `6342e33f-268e-4b67-87ae-1574a2fffbeb`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Tidewater Cartographer | 2 | 788 | 53 | 841 | $0.000369 |  |
| **SUM** | 2 | 788 | 53 | 841 | $0.000369 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 2 | 788 | 53 | 841 | $0.000369 | - |
| every GENERATION in the trace | 2 | 788 | 53 | 841 | $0.000369 | **YES** |
| trace metadata `run_metrics` (reason: run_failed) | 2 |  |  | 841 | $0.000369 | **YES** |
| the APP's own frame-derived total | 2 | 788 | 53 | 841 | $0.000369 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.
