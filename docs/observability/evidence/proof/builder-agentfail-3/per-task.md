# Per task_name - run `f371b3b9-6ca5-4b8b-9f63-9c34249ef440`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Write one short paragraph about the depth of the north reach of the estuary. Use no tools. | 6 | 0 | 0 | 0 | $0.000000 | 6 |
| **SUM** | 6 | 0 | 0 | 0 | $0.000000 | 6 |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 6 | 0 | 0 | 0 | $0.000000 | - |
| every GENERATION in the trace | 6 | 0 | 0 | 0 | $0.000000 | **YES** |
| trace metadata `run_metrics` (reason: failed) | 6 |  |  | 0 | n/a | **YES** |
| the APP's own frame-derived total | 0 | 0 | 0 | 0 | $0.000000 | **YES** |

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role` | 3 | 3 | 0 |  |
| `task_name`  <- this table groups on it | 3 | 3 | 0 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.
