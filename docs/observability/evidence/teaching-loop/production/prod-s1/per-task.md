# Per task_name - run `e3617cd4-8207-4b78-b750-e894ac44e804`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | 2 | 994 | 139 | 1133 | $0.001162 |  |
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
| `agent_role` | 2 | 0 | 0 |  |
| `task_name`  <- this table groups on it | 0 | 0 | 2 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
