# Per task_name - run `3120758e-d7b6-45a7-8f05-28e138a203d9`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| (none) | 2 | 896 | 138 | 1034 | $0.000614 |  |
| **SUM** | 2 | 896 | 138 | 1034 | $0.000614 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 2 | 896 | 138 | 1034 | $0.000614 | - |
| every GENERATION in the trace | 2 | 896 | 138 | 1034 | $0.000614 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 2 |  |  | 1034 | $0.000614 | **YES** |

The APP row is absent: no `--app-figures` was given, so this file compares the table only against Langfuse's own figures.

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role` | 2 | 0 | 0 |  |
| `task_name`  <- this table groups on it | 0 | 0 | 2 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
