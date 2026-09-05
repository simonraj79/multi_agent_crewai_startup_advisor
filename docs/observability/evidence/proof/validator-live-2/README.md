# `validator-live-2` — the re-proof of the billed-cost fix, PAID

Run **2026-09-06** by V-PROOF, second pass, against **`c608953`**
(`fix(observability): the billed-cost lookup is deferred and retried, …`). Same
rules as pass 1: JWKS stand-in on 8093, paid backend on 8000, `RUN_CONCURRENCY=2`,
INFO logging, `readyz-before-pass2.json` saved before any launch, signed in as
`proof-runner`. Same idea text as `../validator-live`, so the two are comparable.

| | |
| --- | --- |
| app run id | `1a0bea14-ffb3-459d-b5fc-f714a76e5f71` |
| Langfuse trace id | `1a0bea14ffb3459db5fcf714a76e5f71` |
| session URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/sessions/1a0bea14-ffb3-459d-b5fc-f714a76e5f71` |
| trace URL | `https://us.cloud.langfuse.com/project/cmto3mj7t06ykad0ipon3ksbw/traces/1a0bea14ffb3459db5fcf714a76e5f71` |
| workflow / gates / env | `idea-validator` / `auto` / `live`, user `proof-runner` |
| terminal | `completed`, 55.9 s |
| frames | 178 |
| observations | 86 — SPAN 18, EVENT 46, AGENT 7, GENERATION 12, TOOL 3 |
| scores | 16, of which 8 `guardrail_passed` |
| app usage | 12 calls, 42,194 / 9,340 / 51,534 tokens, app estimate **$0.0562551** |
| OpenRouter billed | 12 generations, **$0.06441798** |

## The billed-cost resolution — the defect from pass 1 is FIXED

Exporter summary line, verbatim from `../backend-8000-pass2.log`:

```text
langfuse-exporter run=1a0bea14-... frames_enqueued=178 frames_dropped=0
observations_sent=102 http_errors=0 lookup_ok=12 lookup_failed=0
enqueue_p50_us=4 enqueue_p95_us=13
```

**`lookup_ok=12`, `lookup_failed=0` — 12 of 12.** Pass 1 read `lookup_ok=0
lookup_failed=10` on the same flow.

Counted over `langfuse-observations.json`:

| field | result |
| --- | --- |
| `metadata.cost_source` | `openrouter-billed` on **12 of 12** (pass 1: `app-estimate (lookup failed)` on 10 of 10) |
| `metadata.openrouter_cost_usd` | present on **12 of 12** |
| `metadata.provider` | present on **12 of 12** — `Google` and `Google AI Studio` |
| `usageDetails` keys | `{cached, input, output, reasoning, total}` on **12 of 12**; one call carries **557 reasoning tokens**, a split the frame pipeline drops and only the provider knows |
| `costDetails.total` vs OpenRouter's `total_cost` | **0 of 12 differ** — equal to the last decimal on every call |
| `metadata.openrouter_cost_usd` vs `costDetails.total` | **0 of 12 differ** |

Totals:

```text
app estimate   $0.05625510      (compute_cost_usd, local PRICES table)
Langfuse sum   $0.06441798      (sum of costDetails.total over the 12)
OpenRouter sum $0.06441798      (openrouter-figures.json totals)
```

Langfuse and OpenRouter are **identical**; the app's own estimate is **12.7 %
LOW**. That gap was invisible in pass 1 because the trace carried the estimate
and called it the cost. It is now visible in the trace itself, which is the
point of the row.

## The trace still closes on time

The lookups fire at +20 / +60 / +180 s after each generation, and the run's own
span is unaffected:

```text
run span endTime          2026-09-05T17:26:55.255Z
WORKFLOW_END frame ts     2026-09-05T17:26:55.255Z
```

Exact, to the millisecond. The first observation became visible in Langfuse
**209.7 s** after the terminal frame (`langfuse-figures.json`,
`ingestion_visibility`), which is the deferred lookups holding the generation
observations open — as designed — and the trace's own end is not moved by it.

`open-spans.txt`, the **new** instrument:

```text
unfinished spans (non-EVENT observations with endTime null): 0
observations examined: 86
  observations with endTime null, ALL types  : 46
  of those, EVENT (no endTime by construction): 46
  of those, able to end and still open (D3)   : 0
```

## Screenshot

`B5-billed-cost-resolved.png` — the generation `52218e11f6dfc640` open at
`…/traces/1a0bea14ffb3459db5fcf714a76e5f71?observation=52218e11f6dfc640`,
showing `cost_source: "openrouter-billed"`, `openrouter_cost_usd: 0.0045735`,
`provider: "Google"`, `completion_chars: 2021`,
`prompt_fingerprint_basis: "messages"`, `prompt_chars: 4879`, `message_count: 2`
and `null_fields: ""`. The frame was scrolled deliberately so that Langfuse's own
`scope.attributes.public_key` row is **not** in the capture: that row renders the
project public key, and a PNG containing it would fail F3's byte search. Checked
after saving — the key's bytes are not in the file.

## RE-PULLED 2026-09-06 with the tooling fixed at `58a1c0b`

The section below describes the state of this directory as first written, at
`c608953`. **It has since been re-pulled** with
`scripts/observability/pull_langfuse_run.py` at `58a1c0b`, which scrubs identity
fields by exact value only and gives the `fc-` shape rule a UUID boundary. Every
file the tooling writes now carries the run id in full:

```text
langfuse-session.json.id   1a0bea14-ffb3-459d-b5fc-f714a76e5f71
trace.sessionId            1a0bea14-ffb3-459d-b5fc-f714a76e5f71
open-spans.txt run_id      1a0bea14-ffb3-459d-b5fc-f714a76e5f71
```

and `metadata.run_id` reads in full on **85 of the 86** observations.

**One value cannot be repaired by re-pulling, and it is worth naming.**
`trace.metadata.run_id` — and the same field on the single `run` SPAN
`589fbd68245bd87a` — still reads

```text
1a0bea14-ffb3-459d-b5***
```

because **the exporter itself wrote it that way at `c608953`**, before the
value-only scrub landed. That is a fact about this run's *stored trace in
Langfuse*, not about the tooling: the pull is now faithfully reporting what the
API returns. Every run exported after `58a1c0b` writes the id whole — see
`../validator-live-3`. A2's membership check is unaffected here because it runs
over the pass-1 and pass-3 pairs, not over this run; had it run over this one it
would have reported exactly one mismatch, on that `run` span, and it would have
been right to.

The re-pull also exercised the new poller: it stopped after one poll with
`why the wait ended: every generation was billed - nothing left to change`,
12 generations, 12 billed, 0 still on the estimate. `open-spans.txt` reads
`unfinished spans (non-EVENT observations with endTime null): 0`.

## A tooling defect this run exposed, and it damaged evidence (FIXED at `58a1c0b`)

**As first written, every file `pull_langfuse_run.py` wrote for this run had the
run id mangled**:

```text
run_id: 1a0bea14-ffb3-459d-b5<redacted>
```

The UUID is `1a0bea14-ffb3-459d-b5fc-f714a76e5f71` and it contains the substring
**`fc-`**, which is the Firecrawl key prefix the write-time redactor in
`scripts/observability/_common.py::redact_for_disk` scrubs. It fires on a UUID.

Affected here: `durations.md`, `hierarchy.txt`, `langfuse-figures.{json,md}`,
`langfuse-observations.json`, `langfuse-scores.json`, `langfuse-session.json`,
`langfuse-traces.json`, `open-spans.txt`, `per-agent.md`, `per-task.md` — 11
files. **`langfuse-session.json.id` is the field row A1 is verified on**, and in
this directory it reads `1a0bea14-ffb3-459d-b5<redacted>`.

It is a write-time artifact and nothing more: the app-side files
(`app-run.json`, `app-frames.ndjson`, `create.json`, `app-figures.*`) carry the
true id, the live Langfuse API returns it, and the console header in
`B5-billed-cost-resolved.png` renders it in full — `run: 1a0bea14ffb3459db5fcf714a76e5f71`.
A1 is therefore still met for this run, on that evidence rather than on the
saved session file.

A UUID group ends in `fc` about 1.5 % of the time, so this will recur silently.
Owner: whoever owns `scripts/observability/_common.py`. The prefix rules need a
boundary that a hex UUID cannot satisfy.
