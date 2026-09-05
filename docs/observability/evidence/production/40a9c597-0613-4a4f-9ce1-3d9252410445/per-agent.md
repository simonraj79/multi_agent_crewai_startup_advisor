# Per agent_role - run `40a9c597-0613-4a4f-9ce1-3d9252410445`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 2 | 4754 | 855 | 5609 | $0.006415 |  |
| Market evidence analyst | 3 | 9639 | 1466 | 11105 | $0.011802 |  |
| Startup validation scoper | 1 | 1673 | 785 | 2458 | $0.004198 |  |
| Startup validation synthesist | 1 | 7347 | 837 | 8184 | $0.008649 |  |
| Technical feasibility analyst | 2 | 4011 | 564 | 4575 | $0.004704 |  |
| Validation report writer | 3 | 21484 | 9617 | 31101 | $0.052177 |  |
| **SUM** | 12 | 48908 | 14124 | 63032 | $0.087945 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 12 | 48908 | 14124 | 63032 | $0.087945 | - |
| every GENERATION in the trace | 12 | 48908 | 14124 | 63032 | $0.087945 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 12 |  |  | 63032 | $0.077758 | **YES** |

The APP row is absent: no `--app-figures` was given, so this file compares the table only against Langfuse's own figures.

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role`  <- this table groups on it | 12 | 0 | 0 |  |
| `task_name` | 12 | 0 | 0 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
