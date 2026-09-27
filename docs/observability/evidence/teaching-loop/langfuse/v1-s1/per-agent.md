# Per agent_role - run `0813aacd-1550-4eca-b5be-c15ca29d5ffc`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Assessor | 1 | 435 | 73 | 508 | $0.000313 |  |
| Tutor | 1 | 342 | 400 | 742 | $0.001103 |  |
| **SUM** | 2 | 777 | 473 | 1250 | $0.001416 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 2 | 777 | 473 | 1250 | $0.001416 | - |
| every GENERATION in the trace | 2 | 777 | 473 | 1250 | $0.001416 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 2 |  |  | 1250 | $0.001416 | **YES** |

The APP row is absent: no `--app-figures` was given, so this file compares the table only against Langfuse's own figures.

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role`  <- this table groups on it | 2 | 0 | 0 |  |
| `task_name` | 0 | 0 | 2 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
