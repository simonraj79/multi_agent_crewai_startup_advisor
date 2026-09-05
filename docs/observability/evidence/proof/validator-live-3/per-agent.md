# Per agent_role - run `f146e846-7e32-4276-9c9d-d79909a02eec`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 2 | 4032 | 104 | 4136 | $0.001470 |  |
| Guardrail Agent | 1 | 3000 | 10 | 3010 | $0.002288 |  |
| Market evidence analyst | 2 | 5692 | 704 | 6396 | $0.005546 |  |
| Startup validation scoper | 1 | 1698 | 1188 | 2886 | $0.005729 |  |
| Startup validation synthesist | 1 | 7938 | 583 | 8521 | $0.008140 |  |
| Technical feasibility analyst | 2 | 3736 | 656 | 4392 | $0.004969 |  |
| Validation report writer | 2 | 11283 | 5433 | 16716 | $0.028836 |  |
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
| `agent_role`  <- this table groups on it | 11 | 0 | 0 |  |
| `task_name` | 10 | 1 | 0 |  |

TRACE-CONTRACT.md section 3 puts both keys on every observation, so a non-zero ANCESTOR column is a finding about the exporter - even though the grouping above is still correct, because the walk found the value.

---

## V-RECON — B1 on the FINAL code, where this table's cost column is the BILL

Added 2026-09-06 by **V-RECON**, the named verifier for B1. The table above was
regenerated from the live Langfuse API on 2026-09-06 and is **byte-identical**
to the committed copy (as are `per-task.md`, `durations.md` and
`hierarchy.txt`). Grouping is `metadata.agent_role` on each GENERATION.

**This is the first proof run whose per-agent cost column is not an estimate.**
`metadata.cost_source` reads `openrouter-billed` on **11 of 11**, so the
$0.056977 SUM above is OpenRouter's own billed figure, not `compute_cost_usd`'s.

### Does the SUM equal (a) the trace, (b) the app SNAPSHOT, (c) OpenRouter's bill?

| total | calls | input | output | cost | equals the SUM row? |
| --- | ---: | ---: | ---: | ---: | --- |
| this file's SUM row (Langfuse, grouped by agent) | 11 | 37 379 | 8 678 | $0.05697687 | — |
| (a) every GENERATION in the trace | 11 | 37 379 | 8 678 | $0.05697687 | **YES** |
| (b) the app's `GET /api/runs/{id}` snapshot `usage` | 11 | 37 379 | 8 678 | **$0.05268975** | tokens **YES**, cost **NO** |
| (c) OpenRouter `GET /api/v1/generation?id=`, 11 of 11 found | 11 | 37 379 | 8 678 | **$0.05697687** | **YES** |

The one cell that differs is the app's own estimate, $0.00428712 (7.52 %) LOW —
and it is now the only column that is an estimate.

### Per agent: the app's estimate against the bill, and where the gap sits

| agent_role | calls | app estimate | OpenRouter billed | billed ÷ est | reasoning tok | endpoint tier(s) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Community demand analyst | 2 | $0.00146960 | $0.00146960 | 1.0000 | 0 | default |
| Guardrail Agent | 1 | $0.00228750 | $0.00228750 | 1.0000 | 0 | default |
| **Market evidence analyst** | 2 | $0.00346760 | $0.00554608 | **1.5994** | 0 | **default + priority** |
| Startup validation scoper | 1 | $0.00572850 | $0.00572850 | 1.0000 | **919** | default |
| Startup validation synthesist | 1 | $0.00813975 | $0.00813975 | 1.0000 | 0 | default |
| **Technical feasibility analyst** | 2 | $0.00276080 | $0.00496944 | **1.8000** | 0 | priority |
| Validation report writer | 2 | $0.02883600 | $0.02883600 | 1.0000 | 0 | default |
| **SUM** | 11 | **$0.05268975** | **$0.05697687** | 1.0814 | 919 | |

**`Market evidence analyst` at 1.5994 is the sharpest single fact in this
file.** Its two calls are the same model on the same `:nitro` slug and they
were served by **different endpoints** — one `default`, one `priority` — so its
ratio is a blend of 1.0 and 1.8. Routing is per call, which is why no fixed
multiplier can correct the estimate and why the billed figure has to be fetched.
Full working, including the endpoint ids, in `RECONCILIATION.md` §7B.

The scoper's **919 reasoning tokens** bill at ratio exactly 1.0000, confirming
for the third run running that reasoning is charged at the completion rate and
is already inside `native_tokens_completion`.
