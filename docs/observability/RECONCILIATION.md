# Reconciliation — the app, Langfuse and OpenRouter, side by side

Written **2026-09-06** by **V-RECON**, an Opus 5 verifier who built none of this
code and edited nothing under `src/`, `tests/`, `scripts/` or `frontend/`.
This file is the DoD artifact for **E5** and for **E1**, and it carries the
verdicts for the six rows V-RECON owns: **A2, B1, B2, B4, E1, E5** (and
**D5 = A2**).

**Every cell that differs has a named cause.** "Close enough" appears nowhere.

---

## 0. What was measured, and against what

| | |
| --- | --- |
| runs | the four **paid** proof runs of `evidence/proof/RUNS.md`, plus the concurrency pair for A2. The two synthetic runs (`cancelled`, `capture-on`) are excluded from every cost table on purpose: their usage is fabricated by the no-cost doubles and `environment=synthetic` exists so it never enters a cost view |
| code the runs were made on | **`e68dac4`** (`RUNS.md` and its two qualifications are the authority; `7417270` and `ad6a696` landed after, and nothing here was measured against `ad6a696`) |
| app side | each run's saved `app-run.json` + `frames.ndjson` → `app-figures.json` (`pull_app_run.py --from-files`), which reports the frame-derived total **and** the `GET /api/runs/{id}` snapshot separately |
| Langfuse side | the **live public API**, re-pulled 2026-09-06 (`pull_langfuse_run.py`), project `cmto3mj7t06ykad0ipon3ksbw` |
| OpenRouter side | `GET /api/v1/generation?id=` per generation id (`pull_openrouter.py`) — billed cost, native tokens, cached tokens, reasoning tokens, serving provider |
| three-way | `reconcile.py --app … --langfuse … --openrouter …` **with** network, so E1(c) is a measurement rather than `NOT CHECKED` |

### Two passes, and which one each section is about

**§1 – §7 reconcile PASS 1**: the four runs of `RUNS.md` made at `e68dac4`,
plus the concurrency pair. **§7A reconciles PASS 2**: the three re-proof runs
made at `c608953`, where the billed-cost lookup works. Where the two disagree,
pass 2 is the current state of the code and pass 1 is history that explains why
the fix was made — every §1–§7 statement about `cost_source` and about what a
Langfuse reader can see is a statement about **pass-1 traces** and is corrected
in §7A. Nothing from pass 1 was re-run or rewritten to match pass 2: a
measurement of `e68dac4` stays a measurement of `e68dac4`.

### Two things about the tooling that a reader must know

1. **The Langfuse pull was re-run against the live API and reproduces the
   committed evidence byte for byte.** `per-agent.md`, `per-task.md`,
   `durations.md` and `hierarchy.txt` for `validator-live` and `brief-live`
   were regenerated into a scratch directory 40 minutes after V-PROOF's pull
   and `cmp` reports them **identical**. Only `langfuse-figures.md` differs,
   in the ingestion-visibility block, because the re-pull used `--no-poll`.
   The membership check was re-run **live** (not from the saved files) and
   reproduces V-PROOF's result exactly — see §6.

2. **`scripts/observability/pull_langfuse_run.py` does not import at the
   working tree.** Another agent is mid-edit on it (the D3 EVENT/`can_end`
   split, `git diff --stat` = +110/−11) and the file currently raises
   `SyntaxError: unterminated string literal (detected at line 1471)`, which
   blocks `membership_check.py` and `reconcile.py` too, since both import it.
   V-RECON edits nothing under `scripts/`, so the **committed `HEAD` copies**
   of `_common.py`, `pull_app_run.py`, `pull_langfuse_run.py`,
   `pull_openrouter.py`, `reconcile.py` and `membership_check.py` were
   materialised with `git show HEAD:…` into a scratch directory and driven from
   there with the repository's `.env` loaded. The other five files are
   byte-identical to the working tree; only `pull_langfuse_run.py` differs.
   Nothing was stashed, reverted or fixed.

   **RESOLVED before §7A was written.** That edit has landed. All six scripts
   now compile at the working tree
   (`py_compile` over each, no exception), `pull_langfuse_run.py` and
   `reconcile.py` are the only two still modified there, and **every pass-2
   figure in §7A was produced by the working-tree tooling**, not by a `HEAD`
   copy. §1 – §7 keep the `HEAD`-copy provenance they were measured with.

---

## 1. Totals, per paid run — app vs Langfuse vs OpenRouter

The **app** column is `GET /api/runs/{id}`'s own `usage` snapshot; on all four
runs it equals the frame-derived total field for field
(`app-figures.md`, "Frames versus the app's own snapshot": five rows, `yes`
five times), so the app does not disagree with itself anywhere below.

### 1.1 `validator-live` — `f4c8c779-52f2-40e1-9351-2668ea276ae4`, `idea-validator`, completed

| metric | app snapshot | Langfuse session | OpenRouter | verdict | Diagnosis |
| --- | ---: | ---: | ---: | --- | --- |
| calls | 10 | 10 | 10 records found, 0 not found | agree | — |
| input tokens | 29 816 | 29 816 | 29 816 (native) | agree | — |
| output tokens | 6 371 | 6 371 | 6 371 (native) | agree | — |
| total tokens | 36 187 | 36 187 | 36 187 (native) | agree | — |
| cost (USD) | $0.03823525 | $0.03823525 | **$0.03823525 billed** | agree | — |

Nothing differs. Two facts that make the agreement meaningful rather than
lucky: (a) OpenRouter's **normalised** counts are 29 975 / 5 751, which do
*not* match and are not meant to — the like-for-like figures are the native
ones, and `openrouter.md` prints both so the wrong pair cannot be quoted by
accident; (b) the Langfuse cost is the **app's estimate**, not a billed figure
(`metadata.cost_source = "app-estimate (lookup failed)"` on all ten), and it
happens to equal the bill because no call on this run hit the prompt cache.

### 1.2 `brief-live` — `6586c854-3ca3-44c4-a587-eb6a3ef01962`, `brief-flow`, completed

| metric | app snapshot | Langfuse session | OpenRouter | verdict | Diagnosis |
| --- | ---: | ---: | ---: | --- | --- |
| calls | 10 | 10 | 10 records found, 0 not found | agree | — |
| input tokens | 96 787 | 96 787 | 96 787 (native) | agree | — |
| output tokens | 17 606 | 17 606 | 17 606 (native) | agree | — |
| total tokens | 114 393 | 114 393 | 114 393 (native) | agree | — |
| cost (USD) | $0.09759125 | $0.09759125 | **$0.08876144 billed** | **DIFFER, $0.00882981 (9.95 %) high** | **The prompt-cache discount on two calls, $0.00441396 + $0.00441585 = $0.00882981 exactly.** `compute_cost_usd` prices every input token at the full $0.30/M; OpenRouter billed 16 348 + 16 355 = **32 703 cached input tokens** at 10 % of that. Neither the reasoning-token rate nor the `:nitro` spread is involved — §3 has the working |

The app and Langfuse agree because they are the **same number**: the exporter
copies `compute_cost_usd`'s output into `costDetails.total`. This row is one
disagreement (estimate vs bill), not two.

### 1.3 The two failed runs

| metric | `builder-toolfail` app | LF | OR | `builder-agentfail` app | LF | OR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| terminal status | failed | failed | — | failed | failed | — |
| LLM calls that produced tokens | 2 | 2 GENERATIONs | 2 records | **0** | — | 0 records |
| LLM calls that FAILED | 0 | 0 | — | **6** | **6 GENERATIONs, all `level=ERROR`** | **0 records** |
| input tokens | 788 | 788 | 788 | 0 | 0 | 0 |
| output tokens | 53 | 53 | 53 | 0 | 0 | 0 |
| total tokens | 841 | 841 | 841 | 0 | 0 | 0 |
| cost (USD) | $0.0003689 | $0.000368899999 | $0.0003689 | $0.00 | $0.00 | **$0.00** |

Two Diagnosis entries, both named:

- **`builder-toolfail`, cost: Langfuse returns `0.000368899999` where the app
  holds `0.00036889999999999997`.** A **−1.0 × 10⁻¹²** difference on one
  observation (`gen-1788625988-i3TwdQNEaGgndzbftBA7`: app `0.00016139999999999997`,
  Langfuse `0.000161399999`). **Cause: Langfuse stores `costDetails.total` to
  12 decimal places** and truncates below that. It is not the app, not the
  exporter and not the bill — the same run's other observation round-trips
  exactly, and `validator-live` shows the neighbouring effect at 10⁻¹⁹ (pure
  IEEE-754 representation). At $0.0000000000010 it will never matter; it is
  named because E5 says every differing cell gets a cause.
- **`builder-agentfail`, calls: 0 in the app, 6 in Langfuse, 0 at OpenRouter.**
  Not three disagreeing sources — three sources counting three different
  things, all correctly. The app made **six** call attempts (six `llm` frames
  at `stage: before`, seq 20/23/29/32/38/41, each with its own `call_id`) and
  all six were refused by the provider at HTTP 400 (six `stage: error` frames).
  The app's `LLM calls` counter counts **TOKEN** frames, and a refused call
  emits none — its own figures print `failed LLM calls (no tokens): 6` on the
  line below. Langfuse holds exactly six GENERATION observations, one per
  attempt, each keyed on its own opening frame (`frame_seq` 20/23/29/32/38/41,
  `attempt` 1…6), each `level=ERROR`, each with `usageDetails: {}` and
  `costDetails: {}` and `response_id: null`. OpenRouter holds **nothing**,
  because a request refused at 400 never becomes a generation — and that is the
  correct answer, not a gap: **0 + 6 = 6**, and the run cost **$0.00**.

**One further Langfuse-side note on `builder-agentfail`, and it is a real gap
for a cost reader:** `trace.metadata.run_metrics` is **`null`** on that run
alone (the other three carry the final snapshot, `reason: run_completed` /
`run_failed`), because the run emitted no `METRICS_UPDATED` frame before it
failed. A reader who takes trace metadata as the run's cost source gets nothing
from the run that failed earliest. Faithful to the frames; recorded as
`RUNS.md` defect 4 and repeated here because it is an E5-visible cell.

---

## 2. The per-call join on `response_id`

`reconcile.py` joins the app's TOKEN frames, the Langfuse GENERATIONs and the
OpenRouter records on the generation id.

| run | ids in app frames | ids on Langfuse generations | OpenRouter records | rows joining all three | rows joining fewer |
| --- | ---: | ---: | ---: | ---: | --- |
| `validator-live` | 10 | 10 | 10 | **10** | none |
| `brief-live` | 10 | 10 | 10 | **10** | none |
| `builder-toolfail` | 2 | 2 | 2 | **2** | none |
| `builder-agentfail` | 0 | 0 (6 generations, all `response_id: null`) | 0 | **0** | **6 rows join nothing, by construction** — a call refused at HTTP 400 is given no generation id by OpenRouter, so there is no key to join on; the six ERROR generations are matched to the six app `before` frames by `frame_seq`, which is the only join available and is 1:1 |

Every joined row agrees on input tokens, output tokens and app-vs-Langfuse cost
to the value; the only per-row money differences are `brief-live`'s two cached
calls in §3. Zero app calls carry no generation id on the three runs that
produced tokens; zero Langfuse generations lack `metadata.response_id` there.

**The honest limit of the OpenRouter column.** It is an **id lookup**, not a
window enumeration: `GET /api/v1/generation?id=` answers "does this id exist and
what did it cost", and OpenRouter's only per-request ledger is the web console
(`/logs`; `audit/openrouter-forwarding.md` records that `/activity` is an
aggregate dashboard, not a ledger). So this join proves **every call the app
recorded was billed as the app says**, and it cannot by itself prove OpenRouter
served no call the app never recorded. What covers that direction is E1(c) in
§4 — a second reporter would have written its own trace — plus the fact that
the app's frames and Langfuse independently agree on the call count.

---

## 3. `brief-live`'s 9.9 %, attributed to the cent

The run's tokens agree three ways to the token. Only the money differs, and it
is not spread across the run — it lands on **two calls, one agent, one task**.

Per call, app estimate (`in × price_in + out × price_out`, `PRICES` at
`google/gemini-3.5-flash-lite` $0.30/$2.50 and `google/gemini-3.8-flash`
$0.75/$3.75) against OpenRouter's own record:

| generation id | model | in | out | cached | reasoning | app est | billed | delta | `cache_discount` | provider |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `…088-llGgVaOxTWDAq063vgUM` | flash-lite | 880 | 39 | 0 | 0 | $0.000362 | $0.000362 | $0.000000 | null | Google AI Studio |
| `…090-5vRjFbAf9cpScL0N35EW` | flash-lite | 2 930 | 43 | 0 | 0 | $0.000986 | $0.000986 | $0.000000 | null | Google AI Studio |
| `…093-VVxaWEKA2sDV7GgFoy03` | flash-lite | 17 313 | 40 | 0 | 0 | $0.005294 | $0.005294 | $0.000000 | null | Google AI Studio |
| **`…097-Z8k47gHvmpCj2WCRmwdc`** | flash-lite | 27 912 | 43 | **16 348** | 0 | $0.008481 | $0.004067 | **$0.004414** | **$0.00441396** | Google AI Studio |
| **`…101-iF3QXjmImQTlNsVhil5o`** | flash-lite | 38 160 | 1 262 | **16 355** | 0 | $0.014603 | $0.010187 | **$0.004416** | **$0.00441585** | Google AI Studio |
| `…105-t7w03UySvbOvvuvRGJUV` | 3.8-flash | 1 916 | 2 552 | 0 | 2 037 | $0.011007 | $0.011007 | $0.000000 | null | Google |
| `…129-nscdqWJZwFK7PyalekA8` | 3.8-flash | 2 592 | 4 391 | 0 | 3 306 | $0.018410 | $0.018410 | $0.000000 | null | Google |
| `…158-FrBDW35Lw5qdRYxHbYyk` | 3.8-flash | 1 522 | 2 399 | 0 | 2 305 | $0.010138 | $0.010138 | $0.000000 | null | Google |
| `…177-DdVfMYNU9ra4nUmnbo4P` | 3.8-flash | 2 000 | 4 264 | 0 | 3 139 | $0.017490 | $0.017490 | $0.000000 | null | Google |
| `…200-h9JBqTkNVI3HPKEkGxvw` | 3.8-flash | 1 562 | 2 573 | 0 | 2 523 | $0.010820 | $0.010820 | $0.000000 | null | Google |
| **TOTAL** | | 96 787 | 17 606 | **32 703** | 13 310 | **$0.09759125** | **$0.08876144** | **$0.00882981** | | |

**$0.00441396 + $0.00441585 = $0.00882981**, and
`$0.09759125 − $0.08876144 = $0.00882981`. The attribution is exact to the
eighth decimal place — there is no residue to explain.

The rate, derived rather than assumed: `$0.00441396 ÷ 16 348 × 1 000 000 =
$0.270/M` of discount against a $0.30/M list input rate, i.e. **cached input
billed at 10 % of the input rate**, on both calls (the second gives $0.270/M
as well).

**The two hypotheses this rules OUT, each with its own control in the data:**

- **Not the reasoning-token rate.** 13 310 reasoning tokens on this run
  (2 037 + 3 306 + 2 305 + 3 139 + 2 523) sit on five calls whose delta is
  exactly $0.000000, and `validator-live`'s scoper call carries 1 115 reasoning
  tokens and also matches to the cent. Reasoning bills at the completion rate
  and is already inside `native_tokens_completion`, so it cannot drift the
  estimate.
- **Not the `:nitro` provider spread.** All five flash-lite calls here and all
  six on `validator-live` are `google/gemini-3.5-flash-lite:nitro`, and **eleven
  of eleven** were served by `Google AI Studio` or `Google` at the published
  $0.30/$2.50 — nine of them matching the estimate exactly. `config.py`'s
  standing warning that `:nitro` may bill above the published floor (and
  `NITRO_PRICE_FACTOR = 1.8`) is **not** what happened on these two runs; on
  this evidence the only deviation from list price was *downward*, and it was
  the cache.

**And nothing in PASS 1's Langfuse says any of it — a sentence that expired on
2026-09-06.** Read §7A before quoting the paragraph below: at `c608953` the
billed figure, the provider, and the cached/reasoning split are all on the
generation, so a Langfuse reader now sees the bill and the estimate side by
side. What follows is the pass-1 state, which is the reason the fix exists.

`usageDetails.cached` and
`usageDetails.reasoning` are absent on every generation of every paid run,
`metadata.openrouter_cost_usd` and `metadata.provider` are absent, and
`metadata.cost_source` reads `app-estimate (lookup failed)` on **22 of 22**
paid generations — the deferred billed-cost lookup fires inside a 3.0 s
deadline against an endpoint that answers 404 for 60 s+
(`evidence/proof/DEFECT-billed-cost-lookup.md`, `openrouter-index-latency.json`).
So a reader of the trace alone sees $0.09759125 and has no signal that it is
9.9 % high. **That is the single most consequential finding in this file**, and
it is a defect in the exporter's lookup *timing*, not in its arithmetic: the
same lookup driven by hand minutes later returns a real
`BilledCost(total_usd=…, provider='Google', reasoning_tokens=1115, cached_tokens=0)`.

---

## 4. E1 — nothing reaches Langfuse twice

E1 has three parts because "reported twice" can be false in three ways, and one
of them is invisible from inside the session.

### 4a / 4b — inside the session

| run | GENERATION observations | app LLM after-frames | app failed calls | OpenRouter records | duplicate generation ids | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `validator-live` | 10 | 10 | 0 | 10 | 0 | **PASS** |
| `brief-live` | 10 | 10 | 0 | 10 | 0 | **PASS** |
| `builder-toolfail` | 2 | 2 | 0 | 2 | 0 | **PASS** |
| `builder-agentfail` | 6 | 0 | **6** | 0 | 0 | **PASS — see below; `reconcile.py` prints FAIL here and the tool is wrong** |

**`reconcile.py`'s 2a verdict on `builder-agentfail` is a false positive, and
the material to see that is in its own table.** The rule it applies is
"more GENERATIONs than app LLM calls ⇒ duplicate", comparing against the
**after-frame** count, which by construction counts only calls that produced
tokens. On a run where every call was refused that count is 0 and the correct
comparator — attempts — is the very next row it prints (`app calls that FAILED
… 6`). Six attempts, six ERROR generations, one each, distinct `frame_seq` and
`attempt` 1…6: a 1:1 mapping and no duplication of anything.
**Owner: the tooling** (`reconcile.py`, the 2a comparator should be
`after-frames + failed calls`, or should read `before` frames). It is not an
exporter defect and not a Langfuse defect.

### 4c — the second reporter, which no session-scoped check can see

OpenRouter's own broadcast destination writes its *own* Langfuse trace, with no
`sessionId`, so a double-reported call produces two traces that never meet. The
tell is `metadata["openrouter.api_key_name"]`.

| run | window scanned (± 10 min) | traces in window | own traces excluded | **other traces carrying the broadcast key** | verdict |
| --- | --- | ---: | ---: | ---: | --- |
| `validator-live` | 16:23:04 – 16:43:54Z | 16 | 1 | **0** | PASS |
| `brief-live` | 16:24:41 – 16:46:58Z | 28 | 1 | **0** | PASS |
| `builder-toolfail` | 16:23:05 – 16:43:07Z | 13 | 1 | **0** | PASS |
| `builder-agentfail` | 16:24:16 – 16:44:16Z | 19 | 1 | **0** | PASS |

**A zero is only evidence if the instrument can produce a non-zero, so it was
given a positive control.** The same query, over the hours either side of the
configuration change, run 2026-09-06:

```text
BEFORE the exclusion (2026-09-05 08:00 – 13:50:49Z):
  47 traces, 45 carrying openrouter.api_key_name
  by key name: MultiAgentCrewAI 15, LTA_ML_PROBLEM 14, WikiSkills 16
  of those, 44 have sessionId null
AFTER  the exclusion (2026-09-05 13:51 – 18:00Z):
  44 traces, 0 carrying openrouter.api_key_name
the four paid runs' own span (16:33:00 – 16:39:00Z):
  5 traces, 0 carrying openrouter.api_key_name
```

Reproduce it with:

```python
# /api/public/traces, basic auth from LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
hits = [t for t in traces if "openrouter.api_key_name" in (t.get("metadata") or {})]
```

So the detector demonstrably sees 45 broadcast traces when they exist, and
**15 of them were this application's key**, `MultiAgentCrewAI`, in the 5.8 hours
before the change. After it, this app made four paid runs producing 28
generations and **zero** broadcast traces.

**The mechanism is recorded, not inferred:** `audit/openrouter-change.md` — the
destination `8bfe1a26-2ffb-4bbe-a8cf-11839a239f8b` (`multi-agent-crew-ai`) had
`MultiAgentCrewAI` added to its **Excluded API Keys** on 2026-09-05 at
`13:50:49.171Z`, one field of fifteen, with exclusions taking precedence over
inclusions per OpenRouter's own documentation; a 14-of-15 field diff of the
destination JSON before and after proves nothing else moved. That document also
records the trap that matters for anyone re-checking this: **the management API
can neither set nor read the excluded list**, so the API response is not a
faithful record and the UI is the only place it can be read — which is exactly
why the positive control above is the check worth trusting.

Two honest limits: the other two applications' broadcast traces also drop to 0
after the change, which the exclusion does **not** explain (only this app's key
was excluded) and idle apps do; and the window scan is Langfuse-side, so it
would not see a double report that never reached this Langfuse project.

**E1 overall: PASS on all four paid runs.** One reporter per call, no duplicate
generation id, no second trace, and the OpenRouter-side exclusion is the
mechanism that makes it hold.

---

## 5. A2 / D5 — two concurrent runs, zero cross-membership

`validator-live` and `builder-toolfail` were launched **5 ms apart**
(`evidence/proof/concurrent/launch-times.txt`) against a backend with
`RUN_CONCURRENCY=2` and `executor: {"status":"ok","workers":2}`
(`readyz-before.json`).

**They genuinely overlap**, and the strongest form of that statement is not
interleaved frames — it is a containing span
(`evidence/proof/concurrent/overlap.txt`):

| | validator-live | builder-toolfail |
| --- | --- | --- |
| frames | 155 | 43 |
| app frame window | 16:33:04.229 – 16:33:54.540Z (50.311 s) | 16:33:05.199 – 16:33:07.873Z (2.674 s) |
| Langfuse `run` span | 16:33:04.230 – 16:33:54.536Z | 16:33:05.199 – 16:33:07.870Z |
| frames inside the other's window | 0 / 155 | **43 / 43** |
| observations inside the other's window | 0 / 76 | **21 / 21** |

The 0/155 is not idleness and must not be read as one: `validator-live`'s
`scope_idea` model call was in flight throughout, `before` frame seq 7 at
`16:33:04.728Z` and `after` frame seq 8 at `16:33:18.632Z` — a single **13.904 s**
open span that strictly contains the whole of `builder-toolfail`. Serial
execution cannot produce that.

**Membership, re-run live against the API** (not from the saved files):

```text
TOTALS: sessions=2 traces=2 observations=97 mismatches=0 cross-membership=0 no-run_id=0 VERDICT=PASS
```

`evidence/proof/concurrent/membership-check-vrecon.txt`. It reproduces
V-PROOF's committed `membership-check.txt` exactly — the only differences in
the whole file are the `checked at` timestamp and the per-run `session` column
reading `found` (live) where V-PROOF's reads `dir` (from disk). V-PROOF's copy
was **not overwritten**: a second file that agrees is better evidence than a
replaced one.

**And an independent walk, not using that script**, over the two saved
observation exports (`overlap.txt` §3): every observation's
`metadata.run_id` equals its session id — `validator-live` 76 observations with
exactly one distinct value, `builder-toolfail` 21 with exactly one — zero
observations lacking `run_id`, zero shared observation ids, zero shared trace
ids, and no observation of either run naming the other's run id.

**A2 / D5: PASS**, 97 observations walked, every "must be 0" reading 0, by two
instruments.

---

## 6. B1 / B2 — per agent and per task, from Langfuse

Full tables and their three-way comparisons are in each run's `per-agent.md`
and `per-task.md`, regenerated from the live API and byte-identical to the
committed copies. Summary:

| run | grouping | rows | SUM = (a) trace total | SUM = (b) app snapshot | SUM = (c) OpenRouter billed |
| --- | --- | ---: | --- | --- | --- |
| `validator-live` | `agent_role` | 7 agents, 10 calls | **YES** | **YES** | **YES** ($0.03823525) |
| `validator-live` | `task_name` | 6 tasks, 10 calls | **YES** | **YES** | **YES** |
| `brief-live` | `agent_role` | 4 agents, 10 calls | **YES** | **YES** | **NO** — $0.00882981 high, §3 |
| `brief-live` | `task_name` | 3 tasks, 10 calls | **YES** | **YES** | **NO** — same $0.00882981 |

On `brief-live` the entire difference lands on **one agent** (`Senior Research
Analyst …`, 5 calls, $0.029726 estimated / $0.020896 billed) and **one task**
(`research_task`, the same 5 calls) — which is itself the argument for B1/B2
existing: a run-level 9.9 % is a mystery, a per-agent 9.9 % on the one agent
that re-read a 16 k-token page is a cache hit.

Console tree evidence: `validator-live/B1-tree-per-agent.png` (task SPAN
`market_task` → AGENT `Market evidence analyst` → its two GENERATIONs and its
TOOL, each with its own tokens and cost). `brief-live` has no screenshot of its
own; its tree is `brief-live/hierarchy.txt`, drawn from the API. B1 and B2 ask
for one proof run and that run is `validator-live`.

**One tooling defect found here.** Both files print *"Generations whose
identity came from an ANCESTOR rather than their own metadata: 0"*. That line
is computed from `agent_role` alone (`identity_source` is
`"metadata" if meta.get("agent_role") else …`) and is therefore **silent about
`task_name`, the key `per-task.md` groups on**. Measured over the four paid
runs:

| run | generations | `agent_role` from an ancestor | `task_name` from an ancestor |
| --- | ---: | ---: | ---: |
| `validator-live` | 10 | 0 | **1** (Guardrail Agent → `reporting_task`) |
| `brief-live` | 10 | 0 | **2** (both Guardrail Agent → `writing_task`) |
| `builder-toolfail` | 2 | 0 | 0 |
| `builder-agentfail` | 6 | **3** | **3** (→ the AGENT `Channel Sounder`) |

The **grouping** is right — those generations carry `task_name: null` with
`null_fields: "task_name"` declaring it (trace-contract Amendment A1), and the
nearest ancestor with a task name is the task CrewAI actually ran the guardrail
under. Only the provenance line under-reports. It is the visible cause of the
one real difference between the app's own per-task table and Langfuse's:
`app-figures.md` files those calls under **`(none)`**, Langfuse files them under
the task. Langfuse's answer is the more useful one.

---

## 7. B4 — durations, and every delta named

Per-observation pairing, one app frame span against one Langfuse observation of
the same role and label in start order, 1 s tolerance. Side-by-side tables:
`durations-app-vs-langfuse.md` in each run's directory; verdict sections
appended to `validator-live/durations.md` and `brief-live/durations.md`.

| run | paired rows | **outside 1 s** | largest delta | median delta |
| --- | ---: | ---: | --- | ---: |
| `validator-live` | 26 | **0** | 0.119 s — AGENT `Startup validation scoper` | 0.001 s |
| `brief-live` | 17 | **0** | 0.008 s — AGENT `Senior Research Analyst …` | 0.001 s |
| `builder-toolfail` | 7 | **0** | 0.001 s | 0.001 s |
| `builder-agentfail` | 6 | **0** | 0.256 s — AGENT `Channel Sounder` | 0.001 s |

**56 paired rows, 0 outside tolerance, worst 0.256 s.**

The slowest of each kind, which is the question B4 asks:

| run | slowest agent | slowest task | slowest tool |
| --- | --- | --- | --- |
| `validator-live` | Validation report writer 16.626 s | `reporting_task` 18.945 s | `research_market_landscape` 3.789 s |
| `brief-live` | Business Brief Writer … 29.096 s | `writing_task` 88.725 s | `firecrawl_web_scrape_tool` 3.166 s |

### Does DoD §7's timing model account for the deltas? Measured: only partly

§7 says span **start** = the exporter's clock behind a ≤ 0.25 s drain, **end** =
the frame timestamp, and `metadata.frame_ts` = the true start. Over every
observation carrying a `frame_ts`:

| run | observations | max `startTime − frame_ts` | median | above 10 ms |
| --- | ---: | ---: | ---: | ---: |
| `validator-live` | 76 | **+0.016 s** | +0.001 s | 2 |
| `brief-live` | 52 | +0.004 s | +0.001 s | 0 |
| `builder-toolfail` | 21 | +0.001 s | +0.001 s | 0 |
| `builder-agentfail` | 32 | +0.002 s | +0.001 s | 0 |

The drain model is **confirmed and far inside budget** — 16 ms against 250 ms —
and it is therefore **not** what produces the 0.119 s and 0.256 s deltas. The
dominant term is **which frame opens the span**, and the contract's own
`frame_seq` shows it: `Startup validation scoper` opens on `frame_seq: 7`, the
LLM `before` frame at `16:33:04.728Z`, not on the app's agent-execution frame
seq 5 at `16:33:04.622Z`. 0.106 s of frame choice + 0.015 s of drain − 0.002 s
at the end = **0.119 s**, to the millisecond. Same shape on `Channel Sounder`
(0.256 s).

**The cause is upstream of the exporter and is a finding in its own right:**
every one of `validator-live`'s 50 `agent` frames carries `agent_role: None`.
The exporter can only name an agent when a frame supplies the role, and the
first frame that does is that agent's first model call — so an AGENT
observation starts at the agent's **first LLM call**, not at its execution
start. Worth ~0.1 s on a 14 s span here; it would be worth more on an agent
that does a long tool call before its first model call.

### The unpaired rows, none of which is a missing measurement

- **"Langfuse only" agent rows** (1 on `validator-live`, 2 on `brief-live`):
  every one is a `Guardrail Agent`. CrewAI emits no role-named agent frame for
  a guardrail agent, only an `AgentExecutor` pair, so the app-side span carries
  that label while the exporter names the observation from the LLM frame's
  `agent_role`. The intervals match to 3 ms (2.298 s app / 2.296 s Langfuse).
  One interval, two labels, two unmatched rows. Cause: label, not timing.
- **"app only" task rows** (13 / 7 / 2 / 6): `*Crew` and `AgentExecutor`
  boundaries. The contract's tree is node → task → agent; a crew boundary is
  the same interval as its task under another name and gets no observation.
- **"Langfuse only" node rows** (38 / 22 / 10 / 19): **exactly** the EVENT
  observations of each run, verified by id — the set difference is empty on all
  four. A Langfuse EVENT is a point in time with no `endTime`, and the HEAD
  version of `pull_langfuse_run.py::observation_role` has no `EVENT` branch, so
  each falls through to the `node` role and is reported as an unpaired node row
  with `n/a` durations. **A tooling artifact of exactly the family V-PROOF
  recorded as `RUNS.md` defect 5** (`open-spans.txt` counting EVENTs), and the
  working-tree edit in flight — `EVENT`, `ROLE_EVENT`, `can_end()` — fixes both
  at once.

---

## 7A. PASS 2 — the re-proof at `c608953`, and the 12.7 %

Measured 2026-09-06 by V-RECON over the three re-proof runs of `RUNS.md`'s
pass-2 table, made at **`c608953`** (`fix(observability): the billed-cost
lookup is deferred and retried, …`). Every figure here came from the
**working-tree** tooling — which now compiles — and, for anything touching
`validator-live-2`'s run id, from the **live Langfuse API**, for the reason in
§7A.5.

> **The saved `validator-live-2` files predate a re-pull.** Eleven of them were
> written before the `fc-` redaction fix and carry the run id as
> `1a0bea14-ffb3-459d-b5<redacted>`; V-PROOF will re-pull that directory. No
> number in this section was taken from a mangled field: the totals come from
> the app files and the OpenRouter records (neither redacted — measured: zero
> `<redacted>` occurrences in `app-frames.ndjson` and in
> `openrouter-generations.json`) and from a live in-memory API read.

### 7A.1 `validator-live-2` — the three-way table

`1a0bea14-ffb3-459d-b5fc-f714a76e5f71`, `idea-validator`, `auto`, `live`,
`proof-runner`, **completed** in 55.9 s, 178 frames, 86 observations
(SPAN 18, EVENT 46, AGENT 7, GENERATION 12, TOOL 3).

| metric | app snapshot | Langfuse session | OpenRouter | verdict | Diagnosis |
| --- | ---: | ---: | ---: | --- | --- |
| calls | 12 | 12 | 12 records found, 0 not found | agree | — |
| input tokens | 42 194 | 42 194 | 42 194 (native) | agree | — |
| output tokens | 9 340 | 9 340 | 9 340 (native) | agree | — |
| total tokens | 51 534 | 51 534 | 51 534 (native) | agree | — |
| cost (USD) | **$0.05625510** | **$0.06441798** | **$0.06441798 billed** | **app DIFFERS, 12.67 % LOW** | **`:nitro` routed to the PRIORITY endpoint.** Seven cheap-tier calls billed at **exactly 1.8000×** the published floor; the five escalation-tier calls at exactly 1.0000×. $0.00816288, all of it from those seven. Working below |

**The columns have swapped roles since pass 1, and that is the fix.** In pass 1
the app and Langfuse agreed because Langfuse *was* the app's estimate; here
**Langfuse equals OpenRouter to the last decimal** and the app's own estimate is
the odd one out. `metadata.cost_source` is `openrouter-billed` on 12 of 12.

### 7A.2 The 12.7 %, attributed to the cent

`compute_cost_usd`'s estimate against OpenRouter's `total_cost`, per generation,
with the provider's own `service_tier` and `endpoint_id` beside it:

| generation id | model | provider | tier | in | out | reas | est $ | billed $ | **billed ÷ est** |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `…156-3XYsoFWTXtEiPMhfehhc` | 3.8-flash | Google | default | 1 698 | 880 | **557** | 0.0045735 | 0.0045735 | **1.0000** |
| `…163-XQySxMkCBkeNpiJFTTqz` | flash-lite | Google AI Studio | **priority** | 1 770 | 25 | 0 | 0.00059355 | 0.0010683 | **1.8000** |
| `…163-pPG31Cb6q5dKyBNQw1nl` | flash-lite | Google AI Studio | **priority** | 2 008 | 35 | 0 | 0.00068990 | 0.00124182 | **1.8000** |
| `…165-nhHWXCVmPYNPZCNEWdLO` | flash-lite | Google AI Studio | **priority** | 2 134 | 88 | 0 | 0.00086020 | 0.00154836 | **1.8000** |
| `…165-QUTry8cGceuAYPtYTRkM` | flash-lite | Google AI Studio | **priority** | 2 723 | 31 | 0 | 0.00089440 | 0.00160992 | **1.8000** |
| `…167-uAQ8vxVhuQWHlwLB4nsY` | flash-lite | Google AI Studio | **priority** | 2 377 | 556 | 0 | 0.00210310 | 0.00378558 | **1.8000** |
| `…171-SgXqi4rp8j8tpLO2vyVw` | flash-lite | Google AI Studio | **priority** | 3 214 | 601 | 0 | 0.00246670 | 0.00444006 | **1.8000** |
| `…172-I8ALCGX6wpNumCdHm4Rw` | flash-lite | Google AI Studio | **priority** | 3 486 | 620 | 0 | 0.00259580 | 0.00467244 | **1.8000** |
| `…177-swgMZxXjAIKcqQzUBfZ0` | 3.8-flash | Google | default | 8 056 | 700 | 0 | 0.0086670 | 0.008667 | **1.0000** |
| `…183-89vm7slnZAc1bxW57xET` | 3.8-flash | Google AI Studio | default | 4 127 | 3 024 | 0 | 0.01443525 | 0.01443525 | **1.0000** |
| `…204-OqEGCs46fj8PwSFLYqCg` | 3.8-flash | Google | default | 7 423 | 2 764 | 0 | 0.01593225 | 0.01593225 | **1.0000** |
| `…216-blo3uqi8eVqjSydzfB0R` | 3.8-flash | Google | default | 3 178 | 16 | 0 | 0.0024435 | 0.0024435 | **1.0000** |
| **TOTAL** | | | | 42 194 | 9 340 | 557 | **0.05625510** | **0.06441798** | 1.1451 |

`$0.06441798 − $0.05625510 = $0.00816288`, and the **seven priority-tier calls
account for $0.00816288 of it — 100.00 %**. The other five contribute
$0.00000000. (Decimal arithmetic, not float.)

**The cause, named, and the two candidates it is not:**

- **It IS the `:nitro` provider spread — and specifically a `service_tier`
  change between the passes, inside one provider NAME.** `CHEAP_MODEL` is
  `openrouter/google/gemini-3.5-flash-lite:nitro`. `PRICES` records the
  published floor $0.30 / $2.50, and a ratio of exactly 1.8 on both axes means
  the served rate was **$0.54 / $4.50** — precisely the `priority` endpoint
  price for that slug. The generation records say so directly:

  | run | endpoint_id | `service_tier` | ratio |
  | --- | --- | --- | ---: |
  | `validator-live` (pass 1) | `6bd8f433-79e1-416c-b407-1772eb796c9a` | `default` | 1.0000 |
  | `brief-live` (pass 1) | `6bd8f433-…` | `default` | 1.0000 |
  | **`validator-live-2` (pass 2)** | **`bbd2012d-08b2-4b43-9982-012e1ed863d6`** | **`priority`** | **1.8000** |
  | `builder-toolfail` / `-2` | `fe0e0167-572a-482b-8145-f262c1797e79` | `default` | 1.0000 |

  Same slug, same `model_permaslug`, **same `provider_name` "Google AI
  Studio"**, different endpoint, 1.8× the price. So `provider_name` does not
  identify the price: `endpoint_id` and `service_tier` do, and only the
  generation record carries them.

- **It is NOT the reasoning-token rate.** The one call carrying reasoning
  tokens on this run (`…156-3XYsoF…`, 557 of them) bills at ratio **1.0000**,
  as did `validator-live`'s 1 115 and `brief-live`'s 13 310. Reasoning is
  billed at the completion rate and is already inside
  `native_tokens_completion`.

- **It is NOT a stale `PRICES` row.** All five `google/gemini-3.8-flash` calls —
  across two endpoints and two provider names — bill at ratio exactly 1.0000,
  so $0.75 / $3.75 is right; and the flash-lite row's $0.30 / $2.50 is right as
  the *published floor*, which is all `config.py` claims for it. **Nor is it
  cached tokens**: `native_tokens_cached` is 0 on all twelve.

**The defect this exposes is a missing multiplication, and the repository
already holds the constant.** `config.NITRO_PRICE_FACTOR = 1.8` exists for
exactly this and is applied **only** in `builder/budget.py`'s static admission
estimate — `compute_cost_usd` reads `PRICES` and nothing else
(`config.py:504-508`). Applying 1.8 unconditionally would be the wrong fix and
`config.py:164` says why in its own words: measured per-model endpoint ratios
run **1.0× to 9.5×**, "no single constant was ever going to be right", which is
why each model registry row carries its own `cost_in_max_endpoint`. The right
conclusion is the one pass 2 makes available: **the estimate is a floor, the
bill is the number, and the trace now carries both.**

Where the 1.8× lands — entirely on the cheap tier, which is what
`CHEAP_MODEL:nitro` selects:

| agent_role | calls | est $ | billed $ | ratio | tier |
| --- | ---: | ---: | ---: | ---: | --- |
| Market evidence analyst | 3 | 0.00595690 | 0.01072242 | **1.8000** | priority |
| Technical feasibility analyst | 2 | 0.00269660 | 0.00485388 | **1.8000** | priority |
| Community demand analyst | 2 | 0.00155010 | 0.00279018 | **1.8000** | priority |
| Validation report writer | 2 | 0.03036750 | 0.03036750 | 1.0000 | default |
| Startup validation synthesist | 1 | 0.00866700 | 0.00866700 | 1.0000 | default |
| Startup validation scoper | 1 | 0.00457350 | 0.00457350 | 1.0000 | default |
| Guardrail Agent | 1 | 0.00244350 | 0.00244350 | 1.0000 | default |
| **SUM** | 12 | **0.05625510** | **0.06441798** | 1.1451 | |

By task the same split: `market_task` / `feasibility_task` / `sentiment_task` at
1.8000, `reporting_task` / `scoping_task` / `synthesis_task` at 1.0000.

### 7A.3 Per-generation equality, and the trace still closing on time

Read from the **live API**, joined to the OpenRouter records by
`metadata.response_id`:

| check | result |
| --- | --- |
| `costDetails.total` == OpenRouter `total_cost` | **12 of 12**, to the last decimal, 0 differing |
| `metadata.openrouter_cost_usd` == `costDetails.total` | **12 of 12** |
| `metadata.cost_source` | `openrouter-billed` **12 of 12** |
| `metadata.provider` | present 12 of 12 — `Google` ×4, `Google AI Studio` ×8 |
| `usageDetails` keys | `{cached, input, output, reasoning, total}` on **12 of 12** — the split the frame pipeline drops (DoD §7's B1/B2 revision) and only the provider knows |
| generations at `level != ERROR` | 12 of 12 (all `DEFAULT`) |

**The deferred lookups do not hold the run span open.**

```text
run SPAN 589fbd68245bd87a  endTime  2026-09-05T17:26:55.255Z   (live API)
app WORKFLOW_END frame seq 177  ts   2026-09-05T17:26:55.255Z   (app-frames.ndjson)
```

Equal to the millisecond, with the lookups firing at +20 / +60 / +180 s after
each generation. `open-spans.txt`, on its new instrument, reads
`unfinished spans (non-EVENT observations with endTime null): 0` over 86
observations (46 EVENTs open by construction).

**The price of the fix, and it should be stated:** the trace's *completeness*
now lags the run by minutes, not seconds. First observation visible **209.7 s**
after the terminal frame, count stable at **216.7 s** — against **73.5 s** on
pass 1's `validator-live`, a **2.9×** increase, because a generation is held
open until its lookup settles. Nothing is lost and the run is unaffected; but a
reader or a script that pulls a trace 60 s after a run ends will now see less
than one that waits four minutes, and `pull_langfuse_run.py`'s default
`--poll-timeout` is 120 s — **below** the 209.7 s measured here. A pull of this
run at the default would have recorded `stable: false` rather than a short read,
which is the tooling behaving correctly, but it is one more reason not to pass
`--no-poll`.

### 7A.4 E1 on the three pass-2 runs, with the FIXED `reconcile.py`

`reconcile.py` at the working tree now compares **attempts** rather than
after-frames — the pass-1 defect this file recorded as discrepancy #3 — and
prints the completed/failed split beneath it.

| run | app attempts | GENERATIONs | 2a verdict | duplicate generation ids (2b) | OTHER traces carrying `openrouter.api_key_name` (2c) |
| --- | ---: | ---: | --- | ---: | ---: |
| `validator-live-2` | 12 | 12 | **PASS** | 0 | **0** (3 traces in a ±10 min window, 1 its own) |
| `builder-toolfail-2` | 2 | 2 | **PASS** | 0 | **0** |
| `builder-agentfail-2` | 6 | 6 | **PASS** | 0 | **0** |

`builder-agentfail-2` is the case that made pass 1's tool report a false FAIL:
0 completed + 6 failed = 6 attempts against 6 ERROR generations, and it now
reads **PASS**. **Discrepancy #3 is closed by the tooling fix**, and this run is
the proof.

**One thing the new split surfaces that the old comparator hid, and it is a
regression in the exporter, not in the tool.** On `builder-toolfail-2` the
split reads **app 2 completed / 0 failed against Langfuse 0 / 2**:

| | pass 1 `builder-toolfail` | pass 2 `builder-toolfail-2` |
| --- | --- | --- |
| generation A | `level=ERROR`, statusMessage = the RUN's failure text | `level=ERROR`, same |
| generation B | **`level=DEFAULT`**, no statusMessage | **`level=ERROR`**, statusMessage = the RUN's failure text |
| both calls | succeeded, billed $0.0002075 and $0.0001614 | identical, and `cost_source: openrouter-billed` |

So **two successful, billed LLM calls read as errors in Langfuse**, and both
carry the *run's* failure message (`Tool 'read_website_content' failed
during …`) rather than anything about themselves. It went from one such
generation to two between `e68dac4` and `c608953`. The mechanism the contract
describes for exactly this is `TRACE-CONTRACT.md` §6 — on a failed terminal,
"open observations … ended at the same ts, level ERROR" — and the deferred
lookup is what now keeps a generation open long enough to be caught by it;
**that chain is a hypothesis this verifier did not confirm in code** and is for
the exporter's owner. What is measured is the outcome: on a run that fails, a
Langfuse reader filtering `level=ERROR` to find the failed calls gets two calls
that worked and cost money. The E1 *count* is unaffected — 2 = 2 — and the tool
says so in its own sentence ("a level-mapping question rather than a count
one").

### 7A.5 The `fc-` redaction reaches LANGFUSE, not only the saved files

`RUNS.md` and `validator-live-2/README.md` record a tooling defect: the run id
`1a0bea14-ffb3-459d-b5fc-f714a76e5f71` contains the substring **`fc-`**, the
Firecrawl key prefix, and `_common.py::redact_for_disk` scrubbed it in 11 saved
files. The README concludes *"It is a write-time artifact and nothing more …
the live Langfuse API returns it"*.

**That is true of 85 observations and false of two objects.** Read from the
live API:

| object | stored `metadata.run_id` |
| --- | --- |
| 85 of 86 observations | `1a0bea14-ffb3-459d-b5fc-f714a76e5f71` ✓ |
| the **`run` SPAN** `589fbd68245bd87a` | **`1a0bea14-ffb3-459d-b5***`** |
| the **trace** `1a0bea14ffb3459db5fcf714a76e5f71` | **`1a0bea14-ffb3-459d-b5***`** |

The mangling is `***`, the **exporter's** outbound scrub (`ad6a696`, "every
outbound string goes through the scrub"), not `<redacted>`, which is the pull
tooling's — and there is exactly one `***` in the whole live export, on
`run_id`, with zero on either other pass-2 run. The trace's own `sessionId` is
a first-class field and is **correct**, which is why A1 still holds; but the
contract's §3 `run_id` attribute is wrong on the root span and on the trace, in
Langfuse, permanently for this run.

It has a measurable consequence, and the instrument that A2 rests on is the one
that finds it. `membership_check.py`, run live over the three pass-2 sessions:

```text
TOTALS: sessions=3 traces=3 observations=139 mismatches=1 cross-membership=0 no-run_id=0 VERDICT=FAIL

MISMATCHES
  SPAN run id=589fbd68245bd87a
    trace 1a0bea14ffb3459db5fcf714a76e5f71 sessionId=1a0bea14-ffb3-459d-b5fc-f714a76e5f71
    but metadata.run_id=1a0bea14-ffb3-459d-b5***
```

(`evidence/proof/concurrent/membership-check-pass2-vrecon.txt`.) **A2's own
verdict is unaffected** — it is measured on the pass-1 concurrency pair, whose
two run ids contain no `fc-` and which reads 0 mismatches by two instruments —
but the point is sharp: had either concurrent run drawn a UUID with `fc-` in
it, A2 would have failed on a redaction rule rather than on a tracing defect,
and the failure would have looked exactly like cross-membership. A UUID group
ends in `fc` about 1.5 % of the time. **Owner: the scrub, on both sides — the
exporter's (`***`, reaches Langfuse) and the pull tooling's (`<redacted>`,
reaches the files).** A prefix rule needs a boundary a hex UUID cannot satisfy.

### 7A.6 What pass 2 changes in this file's own findings

| pass-1 finding | pass-2 status |
| --- | --- |
| **#1** `brief-live` estimate 9.9 % HIGH (prompt cache) | Not re-run; `brief-flow` was not in pass 2. The cause stands, and pass 2 adds its mirror image: the estimate can be **low** as well as high, and by more |
| **#2** `cost_source = app-estimate (lookup failed)` on 22 of 22 | **FIXED.** `openrouter-billed` on 12 of 12 and 2 of 2; `lookup_ok=12/12` and `2/2`, `lookup_failed=0`. `builder-agentfail-2` reads `app-estimate` on its six generations, which is correct — a call refused at 400 has no billed record to look up |
| **#3** `reconcile.py` E1 2a false FAIL | **FIXED.** The comparator is attempts; `builder-agentfail-2` reads PASS |
| **#4** Langfuse's 12-dp cost storage | Unchanged and still harmless |
| **#5** provenance line silent about `task_name` | **FIXED** per the builder's re-verification; the line is now per key |
| **#6** EVENTs counted as unpaired node rows | **FIXED.** `open-spans.txt` leads with the non-EVENT count, 0 on all three pass-2 runs |
| **#10** `run_metrics` null on the early-failing run | **FIXED.** `builder-agentfail-2` carries `run_metrics.source = "exporter-tally"` with `call_count: 6`; the other two read `source: "app-snapshot"` |
| **#11** the tooling did not compile | **RESOLVED.** All six scripts compile; pass 2 was measured with them |
| — | **NEW #12**: successful billed generations at `level=ERROR` on a failed run (§7A.4) |
| — | **NEW #13**: the `fc-` scrub reaches Langfuse and fails a membership check (§7A.5) |
| — | **STILL OPEN**: `metadata.error_class` is `None` on every error observation of both pass-2 failure runs (`RUNS.md`'s own pass-2 table), so B3/D1's PARTIAL stands — not V-RECON's row, recorded because §9 would otherwise read as if pass 2 fixed everything |

---

## 7B. PASS 3 — the final state at `58a1c0b`

Measured 2026-09-06 by V-RECON over the three re-proof runs of `RUNS.md`'s
pass-3 table, made at **`58a1c0b`** (`fix(observability): the exception class
reaches every error observation, a generation held for its price is never marked
failed, and identity fields are scrubbed by value only`). All figures come from
the working-tree tooling and from the live Langfuse API; the saved
`validator-live-*3*` files are undamaged (their run ids contain no `fc-`), and
`validator-live-2` has been re-pulled — §7B.6.

**This is the pass the final verdicts rest on.** Where §7A and this section
disagree, this one is the code as it now stands.

### 7B.1 `validator-live-3` — the three-way table

`f146e846-7e32-4276-9c9d-d79909a02eec`, `idea-validator`, `auto`, `live`,
`proof-runner`, **completed** in 61.4 s, 167 frames, 81 observations
(SPAN 18, EVENT 42, GENERATION 11, AGENT 7, TOOL 3).

| metric | app snapshot | Langfuse session | OpenRouter | verdict | Diagnosis |
| --- | ---: | ---: | ---: | --- | --- |
| calls | 11 | 11 | 11 found, 0 missing | agree | — |
| input tokens | 37 379 | 37 379 | 37 379 (native) | agree | — |
| output tokens | 8 678 | 8 678 | 8 678 (native) | agree | — |
| total tokens | 46 057 | 46 057 | 46 057 (native) | agree | — |
| cost (USD) | **$0.05268975** | **$0.05697687** | **$0.05697687 billed** | **app DIFFERS, 7.52 % LOW** | **Three `:nitro` calls routed to OpenRouter's PRIORITY endpoint** and billed at exactly 1.8000× the published floor; the other eight at exactly 1.0000×. $0.00428712, 100 % of it from those three |

Langfuse equals OpenRouter to the last decimal; the app's local estimate is the
only column that is an estimate, and the only one that differs.

### 7B.2 The 7.5 %, attributed to the cent — and routing is per CALL

| generation id | model | provider | tier | endpoint_id | in | out | reas | est $ | billed $ | **ratio** |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `…659-U9FowbvkAWavoSe0nql5` | 3.8-flash | Google | default | `10520141-…` | 1 698 | 1 188 | **919** | 0.00572850 | 0.00572850 | **1.0000** |
| `…669-5QuoC6M2UMAGWES2rr8s` | flash-lite | Google AI Studio | default | `6bd8f433-…` | 1 952 | 36 | 0 | 0.00067560 | 0.00067560 | **1.0000** |
| **`…669-oJyryMHtWvx5vCblKbvm`** | flash-lite | Google | **priority** | **`c41311ca-…`** | 1 669 | 25 | 0 | 0.00056320 | 0.00101376 | **1.8000** |
| `…671-oc87DXpA59GvxP8NxtDU` | flash-lite | Google AI Studio | default | `6bd8f433-…` | 2 080 | 68 | 0 | 0.00079400 | 0.00079400 | **1.0000** |
| `…671-Yhp5eTIYrHgMCanh4JNr` | flash-lite | Google AI Studio | default | `6bd8f433-…` | 2 665 | 28 | 0 | 0.00086950 | 0.00086950 | **1.0000** |
| **`…674-AM2MaLzT0eXnJD7VEjPF`** | flash-lite | Google | **priority** | **`c41311ca-…`** | 2 067 | 631 | 0 | 0.00219760 | 0.00395568 | **1.8000** |
| **`…678-0oDPMAnfDwOD32an9Aw2`** | flash-lite | Google | **priority** | **`c41311ca-…`** | 3 027 | 676 | 0 | 0.00259810 | 0.00467658 | **1.8000** |
| `…684-8vd5f93wrLkkCvAAu0XQ` | 3.8-flash | Google | default | `10520141-…` | 7 938 | 583 | 0 | 0.00813975 | 0.00813975 | **1.0000** |
| `…690-2AKrctJTxsN1BwrI6iWo` | 3.8-flash | Google | default | `10520141-…` | 4 320 | 2 847 | 0 | 0.01391625 | 0.01391625 | **1.0000** |
| `…704-s8AccU7wZfIptPVq4C3V` | 3.8-flash | Google | default | `10520141-…` | 6 963 | 2 586 | 0 | 0.01491975 | 0.01491975 | **1.0000** |
| `…717-S88c2kn0Sns6KVr8PyxF` | 3.8-flash | Google | default | `10520141-…` | 3 000 | 10 | 0 | 0.00228750 | 0.00228750 | **1.0000** |
| **TOTAL** | | | | | 37 379 | 8 678 | 919 | **0.05268975** | **0.05697687** | 1.0814 |

`$0.05697687 − $0.05268975 = $0.00428712`. **From the three priority-tier calls:
$0.00428712. From the other eight: exactly $0.00000000.** (Decimal arithmetic.)
Ratio 1.8 on both axes ⇒ a served rate of $0.54 / $4.50 against the published
$0.30 / $2.50 floor — the `priority` endpoint's price for that slug.

**Pass 3 proves something pass 2 could only suggest: the routing is per CALL,
not per run.** In pass 2 all seven `:nitro` calls went priority. Here **five
`:nitro` calls split three priority / two default inside one run**, and the
split is visible at the agent level:

| agent_role | calls | est $ | billed $ | ratio | tier(s) |
| --- | ---: | ---: | ---: | ---: | --- |
| **Market evidence analyst** | 2 | 0.00346760 | 0.00554608 | **1.5994** | **default + priority** |
| Technical feasibility analyst | 2 | 0.00276080 | 0.00496944 | **1.8000** | priority |
| Community demand analyst | 2 | 0.00146960 | 0.00146960 | 1.0000 | default |
| Validation report writer | 2 | 0.02883600 | 0.02883600 | 1.0000 | default |
| Startup validation synthesist | 1 | 0.00813975 | 0.00813975 | 1.0000 | default |
| Startup validation scoper | 1 | 0.00572850 | 0.00572850 | 1.0000 | default |
| Guardrail Agent | 1 | 0.00228750 | 0.00228750 | 1.0000 | default |
| **SUM** | 11 | **0.05268975** | **0.05697687** | 1.0814 | |

`Market evidence analyst`'s **1.5994** is a blend of one 1.0 call and one 1.8
call — the same agent, the same slug, two endpoints, in one run. Three
identical cheap-tier agents came out at 1.0000, 1.5994 and 1.8000. **No fixed
multiplier can correct this estimate**, which is precisely what `config.py:164`
already says of endpoint ratios ("1.0× to 9.5× … no single constant was ever
going to be right") and why `NITRO_PRICE_FACTOR = 1.8` is confined to
`builder/budget.py`'s admission ceiling and must stay out of
`compute_cost_usd`. The answer is the one `58a1c0b` delivers: **fetch the bill**.

Ruled out for the third run in a row: **reasoning** — the scoper's 919 tokens
bill at 1.0000; **cached** — `native_tokens_cached` is 0 on all eleven;
**a stale `PRICES` row** — all six `gemini-3.8-flash` calls bill at exactly
1.0000, and the five flash-lite calls that stayed on the default endpoint do
too, so both rows are right as published floors.

By task, the same split: `feasibility_task` 1.8000, `market_task` 1.5994, and
`reporting_task` / `scoping_task` / `sentiment_task` / `synthesis_task` all
1.0000.

### 7B.3 The generation-level checks

| check | `validator-live-3` | `builder-toolfail-3` | `builder-agentfail-3` |
| --- | --- | --- | --- |
| `metadata.cost_source` | `openrouter-billed` **11/11** | `openrouter-billed` **2/2** | `app-estimate` 6/6 — correct: a call refused at HTTP 400 has no billed record |
| `costDetails.total` == OpenRouter `total_cost` | **11/11** | **2/2** | n/a ($0.00) |
| `usageDetails` keys | `{cached,input,output,reasoning,total}` 11/11 | 2/2 | `{}` 6/6 — no usage on a refused call |
| GENERATION `level` | DEFAULT 11/11 | **DEFAULT 2/2** | ERROR 6/6 |
| `open-spans.txt` | `unfinished spans … : 0` | `: 0` | `: 0` |
| `run_metrics.source` | `app-snapshot` | `app-snapshot` | `exporter-tally` |
| run SPAN `endTime` vs `WORKFLOW_END` frame | `18:08:36.630Z` == `18:08:36.630Z` | — | — |

**`builder-toolfail-3`'s `DEFAULT 2/2` is the closure of discrepancy #12.** In
pass 2 both of that run's generations succeeded, were billed, and were
nonetheless marked `level=ERROR` with the run's failure message; here they read
DEFAULT, and `reconcile.py`'s split agrees on both sides (app 2 completed / 0
failed against Langfuse 2 / 0), where pass 2 read 2/0 against 0/2.

**Ingestion lag is the standing cost of the deferred lookup, and it is
growing.** First observation visible after the terminal frame: **73.5 s**
(pass 1) → **209.7 s** (pass 2) → **466.4 s** (pass 3), stable at the same
466.4 s. That is **7.8 minutes**, and `pull_langfuse_run.py`'s default
`--poll-timeout` is **120 s** — a default pull of this run would have recorded
`stable: false` rather than a short read (the tool behaving correctly), but
anyone scripting around this needs a timeout in minutes, and `--no-poll` on a
fresh run would now read a half-priced trace. V-PROOF's `concurrent-3/README.md`
says the same thing from the operator's side.

### 7B.4 E1 on the three pass-3 runs

`reconcile.py` at the working tree, comparator = **attempts**, network on.

| run | app attempts | GENERATIONs | 2a | 2b duplicate ids | 2c window | **other traces carrying `openrouter.api_key_name`** |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| `validator-live-3` | 11 | 11 | **PASS** | 0 | 17:57:35 – 18:18:36Z | **0** |
| `builder-toolfail-3` | 2 | 2 | **PASS** | 0 | 17:57:36 – 18:17:38Z | **0** |
| `builder-agentfail-3` | 6 | 6 | **PASS** | 0 | 18:06:03 – 18:26:04Z | **0** |

All three windows hold 3 traces, one of which is the run's own. The 2c detector
is the one proved able to see **45** broadcast traces (15 of them this app's
key) in the hours before the OpenRouter destination excluded `MultiAgentCrewAI`
— §4 carries that control, and it is unchanged by pass 3.

Across all three passes: **ten paid runs, E1 PASS on every one**, no generation
id ever carried by two observations, no second reporter in any window.

### 7B.5 A2 / D5 — the pair the final verdict rests on

`validator-live-3` and `builder-toolfail-3` were launched **5 ms apart**
(`concurrent-3/launch-times.txt`) with `RUN_CONCURRENCY=2`
(`readyz-before-pass3.json`: `executor.workers: 2`).

| | validator-live-3 | builder-toolfail-3 |
| --- | --- | --- |
| frames | 167 | 44 |
| app frame window | 18:07:35.262 – 18:08:36.634Z (61.372 s) | 18:07:36.203 – 18:07:38.938Z (2.735 s) |
| frames inside the other's window | 0 / 167 | **44 / 44** |
| observations | 81 | 21 |

Same shape as pass 1: `builder-toolfail-3`'s entire life sits inside **one open
LLM span** of `validator-live-3` — `before` frame seq 7 at 18:07:35.958Z,
`after` seq 8 at 18:07:45.627Z, a 9.669 s gap that strictly contains it. Serial
execution cannot produce a containing span. (`concurrent-3/overlap.txt`.)

`membership_check.py`, **re-run live** against the API rather than from the
saved directories:

```text
TOTALS: sessions=2 traces=2 observations=102 mismatches=0 cross-membership=0 no-run_id=0 VERDICT=PASS
```

`concurrent-3/membership-check-vrecon.txt`. It reproduces V-PROOF's
`membership-check.txt` exactly — the only differences in the whole file are the
timestamp and the `session` column reading `found` where V-PROOF's reads `dir`.
An independent walk over the two saved exports agrees: one distinct
`metadata.run_id` per session, 0 observations without one, 0 shared observation
ids, 0 shared trace ids, and **both traces carry their `metadata.run_id`
whole**.

**What this pair does not prove, stated plainly:** none of the three pass-3 run
ids contains the substring `fc-`, so this pair never presents the scrub with the
string that used to break it. It establishes what A2 asks — two genuinely
concurrent runs with zero cross-membership on the final code — and the direct
evidence for the scrub fix is §7B.6.

### 7B.6 Discrepancy #13, closed — with one value that cannot be repaired

| | before | after `58a1c0b` |
| --- | --- | --- |
| `validator-live-2/langfuse-session.json.id` (saved) | `1a0bea14-ffb3-459d-b5<redacted>` | **`1a0bea14-ffb3-459d-b5fc-f714a76e5f71`** — whole |
| `<redacted>` strings left in that directory's observation export | the run id in 11 files | **86**, and all 86 are `metadata.scope.attributes.public_key`, one per observation — the intended F3 redaction, not damage |
| `validator-live-2` **stored trace** `metadata.run_id` | `1a0bea14-ffb3-459d-b5***` | **still `…b5***`** |

The pull tooling's write-time redactor is fixed and the eleven damaged files are
repaired by the re-pull. The one value a re-pull cannot repair is the one the
**exporter** wrote at `c608953` — the trace's and root span's own
`metadata.run_id` — and `validator-live-2/README.md` says so. Pass-3 traces
carry the id whole, which is the outcome the fix was for; the historical run
keeps its scar, which is the honest record.

### 7B.7 One measured correction to the handoff, and one cosmetic finding

**`error_class` is on every error SPAN, AGENT and TOOL — and not on error
EVENTs or on a failed GENERATION.** Counted over the two pass-3 failure runs:

| run | ERROR observations | carrying `metadata.error_class` | carrying `None` |
| --- | ---: | --- | --- |
| `builder-toolfail-3` | 8 | 5 — TOOL `ValueError`, AGENT / task SPAN / node SPAN / run SPAN `ToolExecutionFailedError` | **3**, all EVENT |
| `builder-agentfail-3` | 18 | 4 — AGENT / task SPAN / node SPAN / run SPAN `BadRequestError` | **14** — 8 EVENT and **6 GENERATION** |

So the class now reaches the spans that matter and `trace.output.error_class` is
populated (`ToolExecutionFailedError`, `BadRequestError`), which is the
substance of what B3/D1 asked for — but "every error observation" is not yet
literally true, and the six ERROR **generations** of `builder-agentfail-3`, the
observations closest to the actual failure, carry `error_class: null`. **B3/D1
are V-PROOF's rows, not V-RECON's**; this is recorded because the figure was
asserted in the handoff and is checkable.

**Cosmetic, and worth one row:** the TOOL observation's `statusMessage` on
`builder-toolfail-3` reads

```text
ValueError: ValueError("Could not resolve hostname: 'sounding-line.invalid'")
```

— the class name prefixed to a message that is already a `repr` naming the same
class. Harmless, and the only observation where the contract's
`ExceptionClass: redacted message` shape doubles up, because the app's tool
frame text was already a repr. Discrepancy #15.

---

## 8. VERDICTS — FINAL

Scope: **all three passes, ten paid runs.** Pass 1 at `e68dac4` (four runs plus
the concurrency pair, §1 – §7), pass 2 at `c608953` (three runs, §7A), pass 3 at
`58a1c0b` (three runs plus the final concurrency pair, §7B). Each sentence says
**which pass it rests on**.

| row | verdict | rests on | the one sentence, naming the file and the figure |
| --- | --- | --- | --- |
| **A2** | **PASS** | **pass 3** (`concurrent-3`), corroborated by pass 1 | `builder-toolfail-3`'s 44 frames and 21 observations all fall inside `validator-live-3`'s window, inside a single 9.669 s open LLM span (`concurrent-3/overlap.txt`), and a **live** re-run of `membership_check.py` over both sessions reads `sessions=2 traces=2 observations=102 mismatches=0 cross-membership=0 no-run_id=0 VERDICT=PASS` (`concurrent-3/membership-check-vrecon.txt`, byte-equal to V-PROOF's apart from timestamp and the `dir`→`found` column), with an independent walk confirming one distinct `metadata.run_id` per session and both traces carrying it **whole**. The pass-1 pair gives the same answer over 97 observations; the pass-2 pair is deliberately not used, because its `fc-` run id would have shown one mismatch that was a redaction bug, not a concurrency one (§7B.5, §7A.5). |
| **D5** | **PASS** | pass 3 | Same artifacts as A2, as the DoD says. |
| **B1** | **PASS** | **pass 3**, with pass 1 for the screenshot | `validator-live-3/per-agent.md`, regenerated from the live API byte-identical to the committed copy, groups all 11 GENERATIONs by `metadata.agent_role` into 7 agents whose SUM — **$0.05697687** — equals the trace total **and OpenRouter's billed total**, because `cost_source` is `openrouter-billed` on 11 of 11; the app's snapshot agrees on every token and is $0.00428712 low on cost, localised by the same table to the two cheap-tier agents that reached the priority endpoint. Tree screenshot `validator-live/B1-tree-per-agent.png`; pass 1 and pass 2 give the same structure with an estimate in the cost column. |
| **B2** | **PASS** | **pass 3** | `validator-live-3/per-task.md` groups the same 11 generations by `metadata.task_name` into 6 tasks with the same SUM and the same three-way comparison, and its **per-key** provenance table now reports `agent_role` 11 own / 0 ancestor and `task_name` 10 own / 1 ancestor — the one ancestor-resolved row being the guardrail call, filed under `reporting_task` from its parent SPAN, declared rather than hidden (discrepancy #5, closed). |
| **B4** | **PASS** | **pass 1** for the bulk, **pass 3** for the exception | Across seven paid runs **94 of 95 paired rows agree within 1 s** (pass 1: 56/56, worst 0.256 s; pass 3: 38/39, worst elsewhere 0.493 s), the slowest agent, task and tool are ranked on every completed run, and the single row outside tolerance is **not a timing disagreement**: one AGENT observation (27.839 s) is being compared with the first of the **two** app executions it actually contains, and against the app's own envelope of both it agrees to **0.009 s** (`validator-live-3/durations.md`, discrepancy #14). |
| **E1** | **PASS on all ten paid runs** | all three passes | GENERATIONs = call ATTEMPTS on every run — pass 1 10/10, 10/10, 2/2, 6/6; pass 2 12/12, 2/2, 6/6; pass 3 11/11, 2/2, 6/6 — with the fixed comparator reading PASS from the tool itself on both later passes; no generation id is carried by two observations anywhere; and **0** other traces carry `openrouter.api_key_name` in any run's window, from a detector proved able to see **45** such traces, 15 of them this app's key, before the OpenRouter destination excluded `MultiAgentCrewAI` on 2026-09-05T13:50:49Z (`audit/openrouter-change.md`). |
| **E5** | **PASS** | all three passes | Ten paid runs put app snapshot, Langfuse session and OpenRouter side by side on calls, input, output, total tokens and cost (§1, §7A.1, §7B.1); **tokens agree three ways on every run**, and every differing cost cell has a named cause measured to the cent — the prompt-cache discount **$0.00882981** (pass 1), the `:nitro` **priority endpoint at exactly 1.8000×**, **$0.00816288** (pass 2) and **$0.00428712** (pass 3), Langfuse's 12-decimal storage (−1 × 10⁻¹²), and a failed-call counter counting tokens rather than attempts. No cell is left at "close enough". |

**The one sentence that changed across the programme.** On pass 1 a Langfuse
reader saw the app's estimate labelled as the cost and had no way to know it was
9.9 % high. On pass 3 the reader sees **the billed figure on the generation**
(`costDetails.total` = OpenRouter's `total_cost`, 11 of 11), the **provider and
endpoint tier** that produced it, the **cached/reasoning split** the frame
pipeline drops, and the app's own estimate beside it in
`trace.metadata.run_metrics.usage.cost_usd` — so the estimate's error is not
merely visible, it is **attributable**: per agent, per task, per call, to the
endpoint that served it.

## 9. Every discrepancy, with its cause and its owner

Rows 1–11 were found on **pass 1** (`e68dac4`), rows 12–13 on **pass 2** (`c608953`), rows 14–15 on **pass 3** (`58a1c0b`). Each row's Owner cell carries its final status. **Eight of the fifteen are closed** — #2, #3, #5, #6, #10, #11, #12, #13. Of the seven that stand, **four are expected by design** (#1 the estimate-vs-bill gap itself, #4 Langfuse's storage precision, #7 the guardrail label, #9 the crew boundaries) and **three are open defects** — #8, #14 and #15, the last cosmetic.

| # | Discrepancy | Where | Named cause | Owner |
| ---: | --- | --- | --- | --- |
| 1 | `brief-live` cost: app/Langfuse $0.09759125 vs billed $0.08876144 — **9.95 % high** | §1.2, §3 | **Prompt-cache discount.** 32 703 cached input tokens on two calls, billed at 10 % of the $0.30/M input rate; `compute_cost_usd` prices every input token at full rate. $0.00441396 + $0.00441585 = $0.00882981, exact. | **Expected model limitation** of a local price table — but see #2, which is why nobody reading Langfuse can find out. |
| 2 | `metadata.cost_source = "app-estimate (lookup failed)"` on **22 of 22** paid generations; `openrouter_cost_usd`, `provider`, `usageDetails.cached`, `usageDetails.reasoning` all absent | every paid run | The deferred billed-cost lookup makes **one** attempt inside `LANGFUSE_BILLED_LOOKUP_DEADLINE_SECONDS = 3.0`, while OpenRouter answers 404 for a fresh generation id from +0.71 s to +60.06 s and beyond. The lookup code itself is correct when driven by hand. | **App bug** (`src/brief_crew/observability/`). Already written up as `DEFECT-billed-cost-lookup.md`; this file adds what it costs — the one number a reader would want (#1) is exactly the one it hides. **FIXED and re-measured (§7A):** `cost_source = openrouter-billed` on 12 of 12 and 2 of 2, `lookup_ok=12/12` and `2/2`, `lookup_failed=0`, and `costDetails.total` equals OpenRouter's `total_cost` on 12 of 12. |
| 3 | `builder-agentfail`: app 0 calls, Langfuse 6 generations → `reconcile.py` prints **E1 2a FAIL** | §1.3, §4a | The comparator uses the app's **after-frame** count, which counts only calls that produced tokens; six refused calls produce none. The correct comparator is attempts, and the tool prints it on the next line (`failed calls: 6`). 0 + 6 = 6, 1:1 with the six ERROR generations. | **Tooling bug** (`scripts/observability/reconcile.py`). Not a duplicate report; E1 passes. **FIXED at the working tree:** the comparator is attempts, and `builder-agentfail-2` reads 6 = 6 PASS (§7A.4). |
| 4 | `builder-toolfail` cost: Langfuse `0.000368899999` vs app `0.00036889999999999997` | §1.3 | **Langfuse stores `costDetails.total` to 12 decimal places.** One observation, −1.0 × 10⁻¹². | **Langfuse** storage precision. Harmless; named because E5 allows no blank cell. |
| 5 | `per-agent.md` / `per-task.md` print "identity came from an ANCESTOR … 0" while 1, 2 and 3 generations respectively had their **`task_name`** resolved from an ancestor | §6 | `identity_source` is computed from `agent_role` only, so the provenance line is silent about the key `per-task.md` groups on. | **Tooling bug** (`pull_langfuse_run.py`). The grouping is correct; only the reporting line is. **FIXED at the working tree** — the provenance line is per key. |
| 6 | 38 / 22 / 10 / 19 "Langfuse only" node rows with `n/a` durations in the B4 tables | §7 | **Exactly the EVENT observations** (verified by id, empty set difference). HEAD's `observation_role()` has no `EVENT` branch, so an EVENT falls through to the `node` role and an observation that cannot have an `endTime` is reported as an unpaired span. | **Tooling bug** (`pull_langfuse_run.py`) — the same family as `RUNS.md` defect 5. **FIXED:** `open-spans.txt` now leads with the non-EVENT count, 0 on all three pass-2 runs. |
| 7 | 1–2 "Langfuse only" AGENT rows per completed run, all `Guardrail Agent`, against unmatched app `AgentExecutor` rows of the same interval | §7 | CrewAI emits no role-named agent frame for a guardrail agent, so the app span is labelled `AgentExecutor` and the observation is named from the LLM frame's `agent_role`. Intervals agree to 3 ms. | **Expected**: a labelling difference between two honest sources. Could be closed by pairing on interval as well as label. |
| 8 | AGENT observations start at the agent's first LLM call, up to **0.256 s** after the app's agent span | §7 | Every app `agent` frame carries `agent_role: None`, so the exporter cannot name an agent until an LLM or tool frame supplies the role. Not the exporter's clock: the drain measures ≤ 0.016 s against a 0.25 s budget. | **App** (frame serializer) — an `agent_role` on the agent frames would close it. Inside B4's tolerance today; would grow on an agent whose first act is a long tool call. |
| 9 | 13 / 7 / 2 / 6 "app only" task rows (`*Crew`, `AgentExecutor`) | §7 | The contract's tree is node → task → agent; a crew boundary is the same interval as its task under a different name and is deliberately given no observation. | **Expected** — a design decision of `TRACE-CONTRACT.md` §2, not a loss. |
| 10 | `trace.metadata.run_metrics` is **null** on `builder-agentfail` | §1.3 | That run emitted no `METRICS_UPDATED` frame before failing, and the exporter is faithful to the frames. | **App** (a run that fails early publishes no metrics snapshot). **FIXED:** `builder-agentfail-2` carries `run_metrics.source = "exporter-tally"` with `call_count: 6`; the other two pass-2 runs read `source: "app-snapshot"`. |
| 11 | `scripts/observability/pull_langfuse_run.py` raises `SyntaxError` at the working tree, blocking `membership_check.py` and `reconcile.py` | §0 | Another agent's in-flight edit (the D3 EVENT/`can_end` split, +110/−11). The committed `HEAD` copies were used instead; nothing was stashed or fixed. | **Transient, another agent's. RESOLVED:** all six scripts compile at the working tree, and every pass-2 figure was produced with them. |
| 12 | **Two successful, BILLED generations carry `level=ERROR`** on `builder-toolfail-2`, both with the RUN's failure message as `statusMessage` | §7A.4 | Measured: one such generation on pass 1, **two** on pass 2, on the same flow. The mechanism the contract names for it is `TRACE-CONTRACT.md` §6's terminal sweep (a failed terminal ends open observations at ERROR) reaching generations the deferred lookup now holds open — **a hypothesis, not confirmed in code here**. | **App** (`src/brief_crew/observability/`). Regression between `e68dac4` and `c608953`. **CLOSED at `58a1c0b`** (§7B.3): `builder-toolfail-3`'s two generations read `level=DEFAULT` with `cost_source: openrouter-billed`, and `reconcile.py`'s split agrees on both sides — app 2 completed / 0 failed against Langfuse 2 / 0, where pass 2 read 2/0 against 0/2. |
| 13 | **The `fc-` scrub reaches LANGFUSE**: `metadata.run_id` on `validator-live-2`'s trace and root `run` SPAN reads `1a0bea14-ffb3-459d-b5***` | §7A.5 | The run id contains the Firecrawl key prefix `fc-`. The `***` form is the **exporter's** outbound scrub (`ad6a696`), distinct from the pull tooling's `<redacted>` that `RUNS.md` already records. 85 of 86 observations are correct; the trace's `sessionId` is correct, so A1 holds. | **App + tooling** — both scrubs. Consequence measured: `membership_check.py` over the three pass-2 sessions read `mismatches=1 VERDICT=FAIL`. **CLOSED at `58a1c0b`** — identity fields are scrubbed by exact value only (§7B.6): `validator-live-2` re-pulled now writes its run id **whole** (`langfuse-session.json.id` = `1a0bea14-ffb3-459d-b5fc-f714a76e5f71`, and all 86 remaining `<redacted>` strings in its observation export are the intended `scope.attributes.public_key` one per observation), and both pass-3 traces carry `metadata.run_id` whole with `mismatches=0`. **One value cannot be repaired**: that run's STORED trace and root span keep `…-b5***`, written by the exporter at `c608953`, and its README says so. |
| 14 | **One AGENT observation covers TWO agent executions**: `Validation report writer` on `validator-live-3` reads 27.839 s in Langfuse against the app's first execution of 14.680 s — the only B4 row outside 1 s across 95 | §7B, `validator-live-3/durations.md` | The app recorded two executions (14.680 s and 13.164 s, a guardrail second pass); Langfuse holds **one** AGENT observation opened on `frame_seq: 131` spanning both, which against the app's own envelope (18:08:07.018 → 18:08:34.866) agrees to **0.009 s**. `TRACE-CONTRACT.md` §2 asks for "one per agent execution start/end". Both generations are nested under it with `attempt: 1` and `attempt: 2`, so no call is lost. | **App** (exporter). Not new in pass 3 — `validator-live-2` merged the same agent — pass 3 is the first run whose durations were paired. Consequences: the slowest-agent *figure* is inflated (its order survives), and the retry is invisible at the agent level. |
| 15 | **Cosmetic double-repr**: the TOOL `statusMessage` reads `ValueError: ValueError("Could not resolve hostname: 'sounding-line.invalid'")` | §7B.7, `builder-toolfail-3` | `58a1c0b` prefixes `ExceptionClass: ` to every error observation's message, and the app's tool frame text was **already** a `repr` naming the class. The only observation where the contract's shape doubles up. | **App** (exporter), cosmetic. Harmless to every check in this file; noted because V-PROOF saw it too and a reader will. |

**Not a discrepancy, and worth saying so:** OpenRouter's *normalised*
`tokens_prompt` / `tokens_completion` (29 975 / 5 751 and 96 627 / 9 702) differ
from every other column by design — they are GPT-tokeniser figures. The
like-for-like comparison is the native count, and `openrouter.md` prints both
so the wrong pair cannot be quoted by accident.
