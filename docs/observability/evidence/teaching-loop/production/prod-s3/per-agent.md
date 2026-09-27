# Per agent_role - run `86371a87-7c50-498a-b32b-4936bd6c0c6a`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Assessor | 1 | 512 | 89 | 601 | $0.000677 |  |
| Tutor | 1 | 468 | 99 | 567 | $0.000698 |  |
| **SUM** | 2 | 980 | 188 | 1168 | $0.001375 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 2 | 980 | 188 | 1168 | $0.001375 | - |
| every GENERATION in the trace | 2 | 980 | 188 | 1168 | $0.001375 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 2 |  |  | 1168 | $0.000764 | **YES** |

The APP row is absent: no `--app-figures` was given, so this file compares the table only against Langfuse's own figures.

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role`  <- this table groups on it | 2 | 0 | 0 |  |
| `task_name` | 0 | 0 | 2 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
