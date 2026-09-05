# Per agent_role - run `45cc3736-ed0b-466a-9dc6-e7f69ff0eea0`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Channel Sounder | 6 | 0 | 0 | 0 | $0.000000 | 6 |
| **SUM** | 6 | 0 | 0 | 0 | $0.000000 | 6 |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 6 | 0 | 0 | 0 | $0.000000 | - |
| every GENERATION in the trace | 6 | 0 | 0 | 0 | $0.000000 | **YES** |
| trace metadata `run_metrics` (reason: failed) | 6 |  |  | 0 | n/a | **YES** |
| the APP's own frame-derived total | 0 | 0 | 0 | 0 | $0.000000 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 3; with no identity at all: 0.
