# Per agent_role - run `6586c854-3ca3-44c4-a587-eb6a3ef01962`

DoD B1, computed from the Langfuse API by grouping GENERATION
observations on their `metadata.agent_role` attribute.

| agent_role | calls | input | output | total | cost | no price |
| --- | --- | --- | --- | --- | --- | --- |
| Business Brief Writer producing decision-ready one-pagers on predictive maintenance for commercial building lifts | 2 | 4592 | 8655 | 13247 | $0.035900 |  |
| Guardrail Agent | 2 | 3084 | 4972 | 8056 | $0.020958 |  |
| Senior Research Analyst specialising in predictive maintenance for commercial building lifts | 5 | 87195 | 1427 | 88622 | $0.029726 |  |
| Strategy Analyst turning raw research on predictive maintenance for commercial building lifts into a defensible point of view | 1 | 1916 | 2552 | 4468 | $0.011007 |  |
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

## V-RECON — B1 on the second flow, and the run where the estimate is 9.9 % high

Added 2026-09-06 by **V-RECON**, the named verifier for B1. The table above was
regenerated from the live Langfuse API on 2026-09-06 and is **byte-identical**
to the committed copy (as are `per-task.md`, `durations.md` and
`hierarchy.txt`). Grouping is `metadata.agent_role` on each GENERATION.

**Screenshot:** this run has none of its own. The console tree evidence B1 cites
is `../validator-live/B1-tree-per-agent.png`; for `brief-live` the equivalent is
`hierarchy.txt` in this directory, drawn from the API, which shows each
GENERATION under its AGENT under its task SPAN. B1 asks for "one proof run", and
that run is `validator-live`; this file is the second run, carried past the bar.

### Does the SUM equal (a) the trace, (b) the app SNAPSHOT, (c) OpenRouter's bill?

| total | calls | input | output | cost | equals the SUM row? |
| --- | ---: | ---: | ---: | ---: | --- |
| this file's SUM row (Langfuse, grouped by agent) | 10 | 96787 | 17606 | $0.09759125 | — |
| (a) every GENERATION in the trace | 10 | 96787 | 17606 | $0.09759125 | **YES** |
| (b) the app's `GET /api/runs/{id}` snapshot `usage` | 10 | 96787 | 17606 | $0.09759125 | **YES** |
| (c) OpenRouter billed, 10 of 10 records found | 10 | 96787 | 17606 | **$0.08876144** | **NO — $0.00882981 (9.95 %) high** |

Tokens agree three ways to the token. **Only the money differs**, and it differs
on one agent.

### Per agent: app estimate versus OpenRouter's billed cost

| agent_role | calls | app estimate (= Langfuse `costDetails.total`) | OpenRouter billed | delta | cached tok | reasoning tok |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Business Brief Writer producing decision-ready one-pagers … | 2 | $0.035900 | $0.035900 | $0.000000 | 0 | 6445 |
| Guardrail Agent | 2 | $0.020958 | $0.020958 | $0.000000 | 0 | 4828 |
| Senior Research Analyst specialising in predictive maintenance … | 5 | $0.029726 | $0.020896 | **$0.008830** | **32703** | 0 |
| Strategy Analyst turning raw research … into a defensible point of view | 1 | $0.011007 | $0.011007 | $0.000000 | 0 | 2037 |
| **SUM** | 10 | **$0.097591** | **$0.088761** | **$0.008830** | 32703 | 13310 |

**The entire run-level gap sits on one agent, and its cause is the prompt
cache.** Two of the Senior Research Analyst's five calls read
16 348 and 16 355 cached input tokens, and OpenRouter's own generation records
carry the discount as a field:

| generation id | in | cached | app est | billed | `cache_discount` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gen-1788626097-Z8k47gHvmpCj2WCRmwdc` | 27912 | 16348 | $0.008481 | $0.004067 | **$0.00441396** |
| `gen-1788626101-iF3QXjmImQTlNsVhil5o` | 38160 | 16355 | $0.014603 | $0.010187 | **$0.00441585** |

$0.00441396 + $0.00441585 = **$0.00882981**, which is the run-level delta to the
eighth decimal place. `compute_cost_usd` prices every input token at the full
$0.30/M; OpenRouter billed those cached tokens at 10 % of it
($0.00441396 ÷ 16 348 × 1e6 = $0.27/M discounted = 0.9 × $0.30/M).

**It is not the reasoning-token rate and not the `:nitro` spread.** 13 310
reasoning tokens on this run (6445 + 4828 + 2037) sit on three agents whose
delta is exactly $0.000000, so reasoning bills at the completion rate and is
already inside `native_tokens_completion`; and every `:nitro` call on both
completed runs was served by `Google AI Studio` or `Google` at the published
rate, with `validator-live`'s six `:nitro` calls matching the estimate to the
cent. Full working in `RECONCILIATION.md`.

**Nothing in the trace says any of this.** `usageDetails.cached` is absent on
all ten generations and `metadata.cost_source` reads
`app-estimate (lookup failed)`, so a reader of Langfuse alone sees $0.097591
and no reason to doubt it (`../DEFECT-billed-cost-lookup.md`).
