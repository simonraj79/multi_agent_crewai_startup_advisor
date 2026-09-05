# Per task_name - run `f146e846-7e32-4276-9c9d-d79909a02eec`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 2 | 3736 | 656 | 4392 | $0.004969 |  |
| market_task | 2 | 5692 | 704 | 6396 | $0.005546 |  |
| reporting_task | 3 | 14283 | 5443 | 19726 | $0.031123 |  |
| scoping_task | 1 | 1698 | 1188 | 2886 | $0.005729 |  |
| sentiment_task | 2 | 4032 | 104 | 4136 | $0.001470 |  |
| synthesis_task | 1 | 7938 | 583 | 8521 | $0.008140 |  |
| **SUM** | 11 | 37379 | 8678 | 46057 | $0.056977 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 11 | 37379 | 8678 | 46057 | $0.056977 | - |
| every GENERATION in the trace | 11 | 37379 | 8678 | 46057 | $0.056977 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 11 |  |  | 46057 | $0.052690 | **YES** |
| the APP's own frame-derived total | 11 | 37379 | 8678 | 46057 | $0.052690 | **YES** |

## Where each generation's identity came from

| identity key | own metadata | an ANCESTOR | nowhere | not recorded |
| --- | --- | --- | --- | --- |
| `agent_role` | 11 | 0 | 0 |  |
| `task_name`  <- this table groups on it | 10 | 1 | 0 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.

---

## V-RECON — B2 on the FINAL code

Added 2026-09-06 by **V-RECON**, the named verifier for B2. The table above was
regenerated from the live Langfuse API on 2026-09-06 and is **byte-identical**
to the committed copy. Grouping is `metadata.task_name` on each GENERATION.
Tree evidence: `hierarchy.txt` beside this file; the console screenshot B2 cites
is `../validator-live/B1-tree-per-agent.png`.

### Does the SUM equal (a) the trace, (b) the app SNAPSHOT, (c) OpenRouter's bill?

| total | calls | input | output | cost | equals the SUM row? |
| --- | ---: | ---: | ---: | ---: | --- |
| this file's SUM row (Langfuse, grouped by task) | 11 | 37 379 | 8 678 | $0.05697687 | — |
| (a) every GENERATION in the trace | 11 | 37 379 | 8 678 | $0.05697687 | **YES** |
| (b) the app's snapshot `usage` | 11 | 37 379 | 8 678 | **$0.05268975** | tokens **YES**, cost **NO** (7.52 % low) |
| (c) OpenRouter billed, 11 of 11 found | 11 | 37 379 | 8 678 | $0.05697687 | **YES** |

### Per task: estimate against bill

| task_name | calls | app estimate | OpenRouter billed | billed ÷ est | endpoint tier(s) |
| --- | ---: | ---: | ---: | ---: | --- |
| **feasibility_task** | 2 | $0.00276080 | $0.00496944 | **1.8000** | priority |
| **market_task** | 2 | $0.00346760 | $0.00554608 | **1.5994** | default + priority |
| reporting_task | 3 | $0.03112350 | $0.03112350 | 1.0000 | default |
| scoping_task | 1 | $0.00572850 | $0.00572850 | 1.0000 | default |
| sentiment_task | 2 | $0.00146960 | $0.00146960 | 1.0000 | default |
| synthesis_task | 1 | $0.00813975 | $0.00813975 | 1.0000 | default |
| **SUM** | 11 | **$0.05268975** | **$0.05697687** | 1.0814 | |

Two tasks carry the whole $0.00428712, and both are cheap-tier tasks whose
`:nitro` calls reached OpenRouter's `priority` endpoint. `RECONCILIATION.md`
§7B has the per-call arithmetic and the endpoint ids.

### The provenance line is fixed, and this file proves it

Pass 1's version of these two files printed one line — *"Generations whose
identity came from an ANCESTOR … 0"* — computed from `agent_role` alone, so it
was silent about the key **this** table groups on. That was V-RECON's
discrepancy #5. The table above it now reports **per key**:

```text
| identity key                            | own metadata | an ANCESTOR | nowhere |
| `agent_role`                            | 11           | 0           | 0       |
| `task_name`  <- this table groups on it | 10           | 1           | 0       |
```

The one ancestor-resolved `task_name` is the `Guardrail Agent` generation, filed
under `reporting_task` from its parent SPAN — correct attribution, and now
declared instead of hidden. `app-figures.md`'s own per-task table still files it
under `(none)`, which is why `reporting_task` reads 3 calls here and 2 there.
