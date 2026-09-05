# `validator-live-3` — pass 3 at `58a1c0b`, PAID, and one half of the A2 pair

Run **2026-09-06** by V-PROOF, third pass, against **`58a1c0b`**
(`fix(observability): the exception class reaches every error observation, a
generation held for its price is never marked failed, and identity fields are
scrubbed by value only`). Same recipe throughout: JWKS stand-in on 8093 started
first, paid backend on 8000 with `RUN_CONCURRENCY=2` under the INFO launcher,
`../readyz-before-pass3.json` saved before any launch, signed in as
`proof-runner`, killed by PID with the backend first. Same idea text as
`../validator-live` and `../validator-live-2`, so all three compare.

| | |
| --- | --- |
| app run id | `f146e846-7e32-4276-9c9d-d79909a02eec` |
| Langfuse trace id | `f146e8467e3242769c9dd79909a02eec` |
| session URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/f146e846-7e32-4276-9c9d-d79909a02eec` |
| trace URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/f146e8467e3242769c9dd79909a02eec` |
| workflow / gates / env / user | `idea-validator` / `auto` / `live` / `proof-runner` |
| tags | `['gates:auto', 'idea-validator', 'mode:run']` |
| terminal | `completed`, 53.4 s |
| frames | 167 |
| observations | 81 — SPAN 18, EVENT 42, AGENT 7, GENERATION 11, TOOL 3 |
| scores | 15 — `run_succeeded`, `run_status`, 6× `task_attempts`, **7× `guardrail_passed`** |
| app usage | 11 calls, 37,379 / 8,678 / 46,057 tokens, app estimate **$0.05268975** |
| OpenRouter billed | 11 generations, **$0.05697687** |

## The lookup counters — `lookup_ok == calls`

`../backend-8000-pass3.log`, verbatim:

```text
langfuse-exporter run=f146e846-7e32-4276-9c9d-d79909a02eec frames_enqueued=167
frames_dropped=0 observations_sent=96 http_errors=0 lookup_ok=11 lookup_failed=0
enqueue_p50_us=3 enqueue_p95_us=11
```

**`lookup_ok=11`, `lookup_failed=0`, and the app made 11 calls** — one resolution
per call, none missed. `frames_enqueued` equals the app's own frame count.

Counted over `langfuse-observations.json`:

| field | result |
| --- | --- |
| `metadata.cost_source` | `openrouter-billed` on **11 of 11** |
| generation `level` | `DEFAULT` on **11 of 11** |
| `metadata.openrouter_cost_usd` / `metadata.provider` | present on **11 of 11** |
| `usageDetails` keys | `{cached, input, output, reasoning, total}` on **11 of 11** |
| `costDetails.total` vs OpenRouter's `total_cost` | **0 of 11 differ** |
| `metadata.prompt_fingerprint_basis` | `messages` on **11 of 11**, with **11 distinct** fingerprints |

```text
app estimate   $0.05268975
Langfuse sum   $0.05697687
OpenRouter sum $0.05697687      identical
```

The app's own estimate is **7.5 % low**; the trace now carries the billed figure
rather than the estimate, which is what makes that gap visible at all.

## The trace closes on its own terminal frame

```text
run span endTime        2026-09-05T18:08:36.630Z
WORKFLOW_END frame ts   2026-09-05T18:08:36.630Z
```

Exact, although the deferred lookups ran on for minutes afterwards (the first
observation became visible **466 s** after the terminal frame — the poller
reports `why the wait ended: every generation was billed - nothing left to
change`).

`open-spans.txt`, the instrument as revised at `58a1c0b`:

```text
unfinished spans (non-EVENT observations with endTime null): 0
observations examined: 81
  observations with endTime null, ALL types  : 42
  of those, EVENT (no endTime by construction): 42
  of those, able to end and still open (D3)   : 0
```

## The `fc-` scrub is gone

`trace.metadata.run_id` reads `f146e846-7e32-4276-9c9d-d79909a02eec` in full, and
so does every file the tooling wrote. Compare `../validator-live-2/README.md`,
where the exporter at `c608953` stored `…-b5***` for a run id containing `fc-`.

## Screenshot

`A1-sessions-list.png` — the Sessions list filtered to `environment = live`,
showing **all ten** paid proof sessions across the three passes, every id equal
to its app run id, every one `proof-runner`, one trace each. The top three rows
are this pass: `f371b3b9…` (agentfail-3), `f0297951…` (toolfail-3) and
`f146e846…` (this run).
