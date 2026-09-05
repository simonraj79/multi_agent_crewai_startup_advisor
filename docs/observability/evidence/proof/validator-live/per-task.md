# Per task_name - run `f4c8c779-52f2-40e1-9351-2668ea276ae4`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| feasibility_task | 2 | 4116 | 574 | 4690 | $0.002670 |  |
| market_task | 2 | 5924 | 623 | 6547 | $0.003335 |  |
| reporting_task | 2 | 7543 | 2752 | 10295 | $0.015977 |  |
| scoping_task | 1 | 1698 | 1417 | 3115 | $0.006587 |  |
| sentiment_task | 2 | 4100 | 127 | 4227 | $0.001548 |  |
| synthesis_task | 1 | 6435 | 878 | 7313 | $0.008119 |  |
| **SUM** | 10 | 29816 | 6371 | 36187 | $0.038235 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 10 | 29816 | 6371 | 36187 | $0.038235 | - |
| every GENERATION in the trace | 10 | 29816 | 6371 | 36187 | $0.038235 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 10 |  |  | 36187 | $0.038235 | **YES** |
| the APP's own frame-derived total | 10 | 29816 | 6371 | 36187 | $0.038235 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.

---

## V-RECON — B2 signed off, plus one difference the two per-task tables have

Added 2026-09-06 by **V-RECON**, the named verifier for B2. The table above was
regenerated from the live Langfuse API on 2026-09-06 and is **byte-identical**
to the committed copy. Grouping is `metadata.task_name` on each GENERATION.
The screenshot is `B1-tree-per-agent.png` in this directory: it shows the task
SPAN `market_task` `24a7e1d59a77be61` with its agent and both generations
nested under it, which is the per-task tree as well as the per-agent one.

### Does the SUM equal (a) the trace, (b) the app SNAPSHOT, (c) OpenRouter's bill?

| total | calls | input | output | cost | equals the SUM row? |
| --- | ---: | ---: | ---: | ---: | --- |
| this file's SUM row (Langfuse, grouped by task) | 10 | 29816 | 6371 | $0.03823525 | — |
| (a) every GENERATION in the trace | 10 | 29816 | 6371 | $0.03823525 | **YES** |
| (b) the app's `GET /api/runs/{id}` snapshot `usage` | 10 | 29816 | 6371 | $0.03823525 | **YES** |
| (c) OpenRouter billed, 10 of 10 records found | 10 | 29816 | 6371 | **$0.03823525** | **YES** |

Per task, the app estimate equals the billed figure on **every** row of this
run (`scoping_task` $0.006587, `market_task` $0.003335, `sentiment_task`
$0.001548, `feasibility_task` $0.002670, `synthesis_task` $0.008119,
`reporting_task` $0.015977). Zero cached tokens on this run; 1115 reasoning
tokens, all in `scoping_task`, billed at the completion rate and therefore
invisible in the delta.

### The one real difference between this table and the app's own per-task table

`app-figures.md`'s per-task table files the guardrail call under **`(none)`**;
this one files it under **`reporting_task`**, so `reporting_task` reads 2 calls
here and 1 there. Both are honest and the Langfuse one is more useful:

- the app's `TOKEN` frame for that call carries no `task_name` (measured: the
  Langfuse GENERATION `metadata.task_name` is `null`, with `null_fields:
  "task_name"` declaring it, exactly as **Amendment A1** of the trace contract
  requires);
- `pull_langfuse_run.py::resolve_identity` then walks to the nearest ancestor
  that has one — the task SPAN `reporting_task` — which is where CrewAI ran the
  guardrail, so the attribution is correct;
- **but the file's own provenance line under-reports it.** "Generations whose
  identity came from an ANCESTOR rather than their own metadata: 0" is computed
  from `agent_role` alone (`identity_source` is set by
  `"metadata" if meta.get("agent_role") else …`), so it is silent about the
  key **this** table groups on. Measured over the four paid runs:
  `agent_role` from an ancestor 0 / 0 / 0 / 3, `task_name` from an ancestor
  **1** (validator-live) / **2** (brief-live) / 0 / 3 (builder-agentfail).
  A tooling defect in the reporting line, not in the grouping — the numbers in
  the table are right. Recorded in `RECONCILIATION.md`'s discrepancy list.
