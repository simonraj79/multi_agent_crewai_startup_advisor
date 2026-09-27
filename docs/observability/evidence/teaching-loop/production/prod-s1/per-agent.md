# Per agent_role - run `e3617cd4-8207-4b78-b750-e894ac44e804`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Assessor | 1 | 527 | 73 | 600 | $0.000613 |  |
| Tutor | 1 | 467 | 66 | 533 | $0.000549 |  |
| **SUM** | 2 | 994 | 139 | 1133 | $0.001162 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 2 | 994 | 139 | 1133 | $0.001162 | - |
| every GENERATION in the trace | 2 | 994 | 139 | 1133 | $0.001162 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 2 |  |  | 1133 | $0.000646 | **YES** |

The APP row is absent: no `--app-figures` was given, so this file compares the table only against Langfuse's own figures.

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role`  <- this table groups on it | 2 | 0 | 0 |  |
| `task_name` | 0 | 0 | 2 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
