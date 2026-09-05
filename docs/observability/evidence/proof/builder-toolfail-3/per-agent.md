# Per agent_role - run `f0297951-e1ff-49a1-90f6-725d06d9b112`

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

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role`  <- this table groups on it | 2 | 0 | 0 |  |
| `task_name` | 2 | 0 | 0 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
