# Per agent_role - run `f4c8c779-52f2-40e1-9351-2668ea276ae4`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Community demand analyst | 2 | 4100 | 127 | 4227 | $0.001548 |  |
| Guardrail Agent | 1 | 2893 | 16 | 2909 | $0.002230 |  |
| Market evidence analyst | 2 | 5924 | 623 | 6547 | $0.003335 |  |
| Startup validation scoper | 1 | 1698 | 1417 | 3115 | $0.006587 |  |
| Startup validation synthesist | 1 | 6435 | 878 | 7313 | $0.008119 |  |
| Technical feasibility analyst | 2 | 4116 | 574 | 4690 | $0.002670 |  |
| Validation report writer | 1 | 4650 | 2736 | 7386 | $0.013747 |  |
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

## V-RECON — B1 signed off, and the third total the table above cannot carry

Added 2026-09-06 by **V-RECON**, the named verifier for B1. Everything above
this line is `pull_langfuse_run.py`'s output and was **regenerated from the
live Langfuse API at 2026-09-06T01:15 +08:00 and is byte-identical** to the
committed copy V-PROOF pulled 40 minutes earlier
(`cmp` against a fresh `--out` directory: identical, along with `per-task.md`,
`durations.md` and `hierarchy.txt`). The grouping is `metadata.agent_role` on
each GENERATION observation, read from the API, not from any app file.

**The console screenshot B1 asks for is `B1-tree-per-agent.png` in this
directory** — the trace tree with `market_task` `24a7e1d59a77be61` → AGENT
`Market evidence analyst` `5110f385afb7793c` → GENERATION `29d9745e799a00bf`
(attempt 1), TOOL `research_market_landscape` `a6c68222501bc21d`, GENERATION
`6887832fcf5eaaa6` (attempt 2), each generation carrying its own tokens and
cost under its own agent.

### Does the SUM equal (a) the trace, (b) the app SNAPSHOT, (c) OpenRouter's bill?

| total | calls | input | output | cost | equals the SUM row? |
| --- | ---: | ---: | ---: | ---: | --- |
| this file's SUM row (Langfuse, grouped by agent) | 10 | 29816 | 6371 | $0.03823525 | — |
| (a) every GENERATION in the trace | 10 | 29816 | 6371 | $0.03823525 | **YES** |
| (b) the app's `GET /api/runs/{id}` **snapshot** `usage` | 10 | 29816 | 6371 | $0.03823525 | **YES** |
| (c) OpenRouter `GET /api/v1/generation?id=`, 10 of 10 found | 10 | 29816 | 6371 | **$0.03823525 billed** | **YES** |

Row (b) is the snapshot, not the frame-derived figure the table above uses;
`app-figures.md`'s "Frames versus the app's own snapshot" shows the app
agreeing with itself on all five fields, so (b) and the app row above are the
same number arrived at two ways.

### Per agent: app estimate versus OpenRouter's billed cost

| agent_role | calls | app estimate (= Langfuse `costDetails.total`) | OpenRouter billed | delta | cached tok | reasoning tok |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Community demand analyst | 2 | $0.001548 | $0.001548 | $0.000000 | 0 | 0 |
| Guardrail Agent | 1 | $0.002230 | $0.002230 | $0.000000 | 0 | 0 |
| Market evidence analyst | 2 | $0.003335 | $0.003335 | $0.000000 | 0 | 0 |
| Startup validation scoper | 1 | $0.006587 | $0.006587 | $0.000000 | 0 | **1115** |
| Startup validation synthesist | 1 | $0.008119 | $0.008119 | $0.000000 | 0 | 0 |
| Technical feasibility analyst | 2 | $0.002670 | $0.002670 | $0.000000 | 0 | 0 |
| Validation report writer | 1 | $0.013747 | $0.013747 | $0.000000 | 0 | 0 |
| **SUM** | 10 | **$0.038235** | **$0.038235** | **$0.000000** | 0 | 1115 |

The scoper's 1115 reasoning tokens cost exactly what the estimate says, which
settles a question `RECONCILIATION.md` asks on the other run: reasoning tokens
are billed at the completion rate and are already inside
`native_tokens_completion`, so they are not a source of drift.

### The one thing this table's cost column is NOT

`costDetails.total` here is the **app's own price-table estimate**, not a
billed figure, on every one of the ten generations —
`metadata.cost_source` reads `app-estimate (lookup failed)` and
`metadata.openrouter_cost_usd` / `metadata.provider` /
`usageDetails.cached` / `usageDetails.reasoning` are absent, because the
billed-cost lookup fires inside a 3.0 s deadline against an endpoint that
answers 404 for 60 s+ (`../DEFECT-billed-cost-lookup.md`). It agrees with the
bill to the cent **on this run**, and the reason it does is that no call here
hit the prompt cache. It does not agree on `brief-live`.
