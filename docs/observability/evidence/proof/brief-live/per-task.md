# Per task_name - run `6586c854-3ca3-44c4-a587-eb6a3ef01962`

DoD B2, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.task_name` attribute.

| task_name | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| analysis_task | 1 | 1916 | 2552 | 4468 | $0.011007 |  |
| research_task | 5 | 87195 | 1427 | 88622 | $0.029726 |  |
| writing_task | 4 | 7676 | 13627 | 21303 | $0.056858 |  |
| **SUM** | 10 | 96787 | 17606 | 114393 | $0.097591 |  |

## Does the SUM row equal the run total?

| total | calls | input | output | total tokens | cost | equals the SUM row? |
| --- | --- | --- | --- | --- | --- | --- |
| this table's SUM row | 10 | 96787 | 17606 | 114393 | $0.097591 | - |
| every GENERATION in the trace | 10 | 96787 | 17606 | 114393 | $0.097591 | **YES** |
| trace metadata `run_metrics` (reason: run_completed) | 10 |  |  | 114393 | $0.097591 | **YES** |
| the APP's own frame-derived total | 10 | 96787 | 17606 | 114393 | $0.097591 | **YES** |

Generations whose identity came from an ANCESTOR rather than their own metadata: 0; with no identity at all: 0.

---

## V-RECON — B2 on the second flow

Added 2026-09-06 by **V-RECON**, the named verifier for B2. The table above was
regenerated from the live Langfuse API on 2026-09-06 and is **byte-identical**
to the committed copy. Grouping is `metadata.task_name` on each GENERATION.
Tree evidence: `hierarchy.txt` beside this file; the console screenshot B2 cites
is `../validator-live/B1-tree-per-agent.png`, which shows a task SPAN with its
agent and both of its generations nested under it.

### Does the SUM equal (a) the trace, (b) the app SNAPSHOT, (c) OpenRouter's bill?

| total | calls | input | output | cost | equals the SUM row? |
| --- | ---: | ---: | ---: | ---: | --- |
| this file's SUM row (Langfuse, grouped by task) | 10 | 96787 | 17606 | $0.09759125 | — |
| (a) every GENERATION in the trace | 10 | 96787 | 17606 | $0.09759125 | **YES** |
| (b) the app's `GET /api/runs/{id}` snapshot `usage` | 10 | 96787 | 17606 | $0.09759125 | **YES** |
| (c) OpenRouter billed, 10 of 10 records found | 10 | 96787 | 17606 | **$0.08876144** | **NO — $0.00882981 high** |

### Per task: app estimate versus OpenRouter's billed cost

| task_name | calls | app estimate | OpenRouter billed | delta | cached tok | reasoning tok |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| analysis_task | 1 | $0.011007 | $0.011007 | $0.000000 | 0 | 2037 |
| research_task | 5 | $0.029726 | $0.020896 | **$0.008830** | **32703** | 0 |
| writing_task | 4 | $0.056858 | $0.056858 | $0.000000 | 0 | 11273 |
| **SUM** | 10 | **$0.097591** | **$0.088761** | **$0.008830** | 32703 | 13310 |

One task carries the whole difference, and it is the prompt-cache discount on
its last two calls — the working, to the eighth decimal place, is in
`per-agent.md` beside this file and in `RECONCILIATION.md`.

### The `(none)` row this table does not have, and why

Two of the ten generations carry `metadata.task_name: null` (both `Guardrail
Agent` calls, `null_fields: "task_name"`, per trace-contract Amendment A1) and
are filed under `writing_task` by walking to the nearest ancestor that has a
task name — which is where CrewAI ran them. That is why `writing_task` reads
4 calls here and **2** in `app-figures.md`'s own per-task table, whose `(none)`
row holds the other two. The Langfuse attribution is the more useful one; the
file's provenance line ("came from an ANCESTOR … 0") is computed from
`agent_role` only and does not report it. Recorded as a tooling defect in
`RECONCILIATION.md`.
