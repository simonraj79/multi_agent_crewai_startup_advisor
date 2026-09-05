# Durations from Langfuse spans - run `f146e846-7e32-4276-9c9d-d79909a02eec`

DoD B4. Slowest first. The app-side column is in `app-figures.md`;
`reconcile.py` is what puts the two within-1-s comparison side by side.

Run span: 2026-09-05T18:07:35.263000Z -> 2026-09-05T18:08:36.630000Z (61.367 s)

Every figure below is an observation's OWN duration. A child's duration
is never added to its parent's: the contract nests node -> task -> agent
-> tool over one 2 s tool call, and summing that tree reports 6 s.

## Agents

| agent_role | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| Validation report writer | 1 | 27.839 | 27.839 |  |
| Market evidence analyst | 1 | 9.873 | 9.873 |  |
| Startup validation scoper | 1 | 9.507 | 9.507 |  |
| Technical feasibility analyst | 1 | 7.887 | 7.887 |  |
| Startup validation synthesist | 1 | 5.234 | 5.234 |  |
| Community demand analyst | 1 | 3.307 | 3.307 |  |
| Guardrail Agent | 1 | 1.706 | 1.706 |  |

## Tasks

| task_name | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| reporting_task | 1 | 29.568 | 29.568 |  |
| scoping_task | 1 | 10.006 | 10.006 |  |
| market_task | 1 | 9.886 | 9.886 |  |
| feasibility_task | 1 | 7.909 | 7.909 |  |
| synthesis_task | 1 | 5.253 | 5.253 |  |
| sentiment_task | 1 | 3.320 | 3.320 |  |

## Tools

| tool | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| research_market_landscape | 1 | 6.115 | 6.115 |  |
| assess_technical_feasibility | 1 | 4.000 | 4.000 |  |
| analyze_community_sentiment | 1 | 1.862 | 1.862 |  |

## Nodes

| node_id | spans | total s | slowest s | unclosed |
| --- | --- | --- | --- | --- |
| write_report | 1 | 29.876 | 29.876 |  |
| research_market | 1 | 15.499 | 15.499 |  |
| research_feasibility | 1 | 10.782 | 10.782 |  |
| scope_idea | 1 | 10.378 | 10.378 |  |
| synthesize | 1 | 5.562 | 5.562 |  |
| research_sentiment | 1 | 3.754 | 3.754 |  |
| confirm_scope | 1 | 0.002 | 0.002 |  |
| route_scope | 1 | 0.001 | 0.001 |  |
| route_verdict | 1 | 0.001 | 0.001 |  |
| persist | 1 | 0.001 | 0.001 |  |
| review_verdict | 1 | 0.000 | 0.000 |  |

## The B4 answer: the slowest agent, task and tool

| role | label | seconds | observation id |
| --- | --- | --- | --- |
| agent | Validation report writer | 27.839 | a01a05e7ab12d735 |
| task | reporting_task | 29.568 | 9500e495d58b35f6 |
| tool | research_market_landscape | 6.115 | f1aaa83740dd35d1 |

## Slowest individual observations

| role | type | name | seconds | id |
| --- | --- | --- | --- | --- |
| run | SPAN | run | 61.367 | 9b38407b6cc90966 |
| node | SPAN | write_report | 29.876 | b745e52182baf0b7 |
| task | SPAN | reporting_task | 29.568 | 9500e495d58b35f6 |
| agent | AGENT | Validation report writer | 27.839 | a01a05e7ab12d735 |
| node | SPAN | research_market | 15.499 | b1c9d46446eafe00 |
| generation | GENERATION | google/gemini-3.8-flash | 14.648 | eb132fffa8140c01 |
| generation | GENERATION | google/gemini-3.8-flash | 13.135 | 870c635a51269455 |
| node | SPAN | research_feasibility | 10.782 | 4de07b3600ad6248 |
| node | SPAN | scope_idea | 10.378 | 33f1d4138dd168e8 |
| task | SPAN | scoping_task | 10.006 | 917e4442d54909d9 |
| task | SPAN | market_task | 9.886 | 649cbba8f2053a64 |
| agent | AGENT | Market evidence analyst | 9.873 | 6c64f98173c32d9d |
| agent | AGENT | Startup validation scoper | 9.507 | 826d058fce9205a7 |
| generation | GENERATION | google/gemini-3.8-flash | 9.496 | 39ff25b8cb605f62 |
| task | SPAN | feasibility_task | 7.909 | da130dcdec8f4cc3 |
| agent | AGENT | Technical feasibility analyst | 7.887 | 429ab69eba843eb9 |
| tool | TOOL | research_market_landscape | 6.115 | f1aaa83740dd35d1 |
| node | SPAN | synthesize | 5.562 | d6acee545db21015 |
| task | SPAN | synthesis_task | 5.253 | 908617faf04d9b88 |
| agent | AGENT | Startup validation synthesist | 5.234 | 7102102ba575941d |

---

## V-RECON — B4 on the FINAL code, and the ONE row outside tolerance

Added 2026-09-06 by **V-RECON**, the named verifier for B4. Everything above is
the Langfuse side alone, regenerated from the live API **byte-identical** to the
committed copy. The side-by-side is `durations-app-vs-langfuse.md` beside this
file (`reconcile.py --durations-out`, one app span against one observation,
matched on role + label in start order, 1 s tolerance).

### The B4 answer — the slowest of each kind

| the slowest | label | Langfuse s | app s | note |
| --- | --- | ---: | ---: | --- |
| **agent** | Validation report writer (`a01a05e7ab12d735`) | 27.839 | 14.680 | **the one row outside tolerance — see below** |
| **task** | reporting_task | 29.568 | 29.568 | 0.000 s |
| **tool** | research_market_landscape | 6.115 | 6.119 | 0.004 s |

Behind them: agents — scoper 9.507 s, market 9.873 s, feasibility 7.887 s,
synthesist 5.234 s, sentiment 3.307 s, guardrail 1.706 s; tools —
`assess_technical_feasibility` and `analyze_community_sentiment`.
`reporting_task` at 29.6 s of a 61.4 s run is the answer to "why was this run
slow", and the reason is that the report writer ran **twice**.

### 39 paired rows across the three pass-3 runs, **1** outside 1 s

| run | paired | outside 1 s | largest delta | median |
| --- | ---: | ---: | --- | ---: |
| `validator-live-3` | 26 | **1** | 13.159 s — AGENT `Validation report writer` | 0.001 s |
| `builder-toolfail-3` | 7 | 0 | 0.002 s | 0.001 s |
| `builder-agentfail-3` | 6 | 0 | 0.203 s — AGENT `Channel Sounder` | 0.000 s |

### The 13.159 s is not a clock disagreement. It is one observation against two executions

The app recorded **two** `Validation report writer` executions — a
guardrail-driven second pass:

```text
app  seq 129 -> 138   18:08:07.018Z .. 18:08:21.698Z   14.680 s
app  seq 141 -> 150   18:08:21.702Z .. 18:08:34.866Z   13.164 s
```

Langfuse holds **one** AGENT observation for the role,
`a01a05e7ab12d735`, opened on `frame_seq: 131` (the first LLM `before` frame)
and ending at `18:08:34.874Z` — **27.839 s, the envelope of both executions**.
Against the app's own envelope, 18:08:07.018 → 18:08:34.866 = 27.848 s, it
agrees to **0.009 s**. Nothing is mistimed; there is one observation where the
contract asks for two.

`TRACE-CONTRACT.md` §2 says AGENT is "one per agent execution start/end". Both
generations are nested under this single observation and are individually
legible (`attempt: 1` and `attempt: 2`), so no call is lost — but at the agent
level the retry is invisible, and the agent's reported duration includes the
7 ms of dead time between the passes plus, in the general case, however long an
agent waits between executions. Two consequences a reader should know:

1. **The "slowest agent" ranking is inflated.** `Validation report writer`
   reads 27.839 s while no single execution of it exceeded 14.68 s. It is still
   genuinely the slowest agent on this run either way, so the ranking's *order*
   survives; its *figure* does not.
2. **The pairing produces one `app only` row** (`Validation report writer` #2,
   13.164 s) as its counterpart, which is the same fact seen from the other
   side.

Recorded as discrepancy **#14** in `RECONCILIATION.md` §9. Owner: the exporter.
It is not new in pass 3 — `validator-live-2` also ran that agent twice under one
AGENT observation — pass 3 is simply the first run whose durations were paired.

### The §7 timing model still holds where it is testable

`startTime − metadata.frame_ts` over all 81 observations: median **+0.001 s**,
maximum **+0.173 s** (a GENERATION), only 2 above 10 ms — inside the ≤ 0.25 s
drain the DoD §7 model allows, and the largest drain measured on any proof run
so far (pass 1 read 0.016 s, pass 2 0.004 s). The other two pass-3 runs read
0.002 s and 0.001 s.

`Startup validation scoper`'s 0.493 s is both effects added, and they close
exactly: the app's agent span opens at 18:07:35.638Z, the LLM `before` frame it
is exported from is `frame_seq: 7` at 18:07:35.958Z (**0.320 s** of frame
choice — an AGENT observation opens on the agent's first model call, because
the app's `agent` frames carry `agent_role: None`), and the observation's own
`startTime` is 18:07:36.131Z (**0.173 s** of drain). 0.320 + 0.173 = 0.493 s.
Neither is a clock error and both are far inside tolerance.

### The other unpaired rows, unchanged in kind

`Guardrail Agent` appears as one `Langfuse only` row (1.706 s) against an app
span labelled `AgentExecutor` — the label mismatch documented for pass 1 —
and the `*Crew` / `AgentExecutor` boundaries remain `app only` by design.
The `Langfuse only` node rows are the EVENT observations, now correctly
excluded from the D3 instrument (`open-spans.txt` reads
`unfinished spans … : 0`).
