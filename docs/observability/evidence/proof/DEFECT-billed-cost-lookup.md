# Defect, measured on the PAID runs: the billed-cost resolution never succeeds

Found 2026-09-06 by V-PROOF while executing Task 3. Code at `e68dac4`.
Field: `metadata.cost_source` on every GENERATION observation, and the
exporter's own `lookup_ok` / `lookup_failed` counters.

## What was observed

`TRACE-CONTRACT.md` §4 says `metadata.cost_source` is `app-estimate` at
emission and `openrouter-billed` "after the out-of-band resolution below
succeeds", with `metadata.openrouter_cost_usd` and `metadata.provider` set.
`LANGFUSE_RESOLVE_BILLED_COST` defaults to on and `/readyz` confirmed
`resolve_billed_cost: true` before any run.

On all four paid runs the resolution failed for **every** generation:

| run | generations | `lookup_ok` | `lookup_failed` |
| --- | ---: | ---: | ---: |
| `validator-live` f4c8c779… | 10 | **0** | **10** |
| `builder-toolfail` 9becf713… | 2 | **0** | **2** |
| `builder-agentfail` ca13fc73… | 6 (all failed calls, no ids) | 0 | 0 |
| `brief-live` 6586c854… | 10 | **0** | **10** |

(the four `langfuse-exporter …` summary lines in `backend-8000.log`).

Consequently every generation on every paid run carries

```text
metadata.cost_source          = "app-estimate (lookup failed)"
metadata.openrouter_cost_usd  = (absent)
metadata.provider             = (absent)
usageDetails.reasoning        = (absent)
usageDetails.cached           = (absent)
```

`costDetails.total` is therefore the app's local `PRICES` estimate on every
paid observation in Langfuse, and the two token splits §4 says are the only
reason the lookup exists are absent.

## The cause, measured — it is TIMING, not the code

**The exporter's own lookup code is correct.** Driving
`brief_crew.observability.billed_cost.HttpCostLookup` by hand against a
generation id from `validator-live` (`gen-1788625988-JC5jXfntDkNXlKRfCQQ2`),
minutes after the run, answers:

```text
BilledCost(total_usd=0.00658725, provider='Google',
           upstream_usd=None, reasoning_tokens=1115, cached_tokens=0)
```

So the URL, the auth, the parsing and the `BilledCost` shape all work.

**OpenRouter does not index a generation anywhere near fast enough.** One
fresh `POST /chat/completions` (`google/gemini-3.5-flash-lite`, `max_tokens:1`)
was followed by `GET /api/v1/generation?id=` every ~0.5 s for 60 s:
**58 consecutive 404s, from +0.71 s to +60.06 s**, and the same id still
answered 404 twenty minutes later. Raw numbers:
`openrouter-index-latency.json` beside this file.

`config.LANGFUSE_BILLED_LOOKUP_DEADLINE_SECONDS` is **3.0** and the exporter
makes **one** attempt with no retry (`langfuse_exporter.py::_settle_lookup`
cancels the future at the deadline and counts `lookup_failed`). A window that
closes at 3 s cannot ever catch a record that does not exist at 60 s.

By contrast `scripts/observability/pull_openrouter.py` "retries a 404 four
times at 5 s" and resolved **all 22** ids for these runs — because it ran
minutes later, not seconds.

## Why it is invisible without looking

Nothing fails. `http_errors=0`, `frames_dropped=0`, the run is unaffected, and
`cost_source` honestly reads `app-estimate (lookup failed)` — which is exactly
the distinction §4 designed in. The defect is that the *succeeding* branch is
unreachable in practice on this provider, so the feature ships permanently off
while reporting itself as on (`/readyz` says `resolve_billed_cost: true`).

## Not fixed here

V-PROOF built none of this code and edited none of it. Owner: whoever owns
`src/brief_crew/observability/`. The shape of a fix is a deferred resolution
(a delay or a retry schedule measured in tens of seconds, or a post-run sweep)
rather than a larger deadline on a synchronous attempt — 60 s of blocking on
the export thread is not the trade the contract wants.
