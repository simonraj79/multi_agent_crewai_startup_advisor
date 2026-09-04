# Pre-flight for the first paid validator run

Prepared 2026-08-29. Scope: verify credentials, trace the live path, estimate
cost, and name the failure modes — **before** anyone spends money.

> **Editorial note (2026-08-30).** This document originally recorded the live
> *answers* to each check — account balances, spend limits, index counts. Those
> are the author's own account state, they go stale the moment a run happens, and
> they do not belong in a public repository. They have been replaced with the
> check to run and the answer you need to see. Every figure that survives below
> is either a published price, a documented platform limit, or a measurement
> taken from this repository's own artifacts.

---

## I spent nothing

No validator ran. No crew, no flow, no benchmark, no LLM call of any kind. No
Firecrawl scrape. Nothing was written to Pinecone.

Every call I made was free and read-only. The complete list, verbatim:

| Service | Call | Why it is free |
| --- | --- | --- |
| OpenRouter | `GET https://openrouter.ai/api/v1/key` | Quota metadata. No inference. |
| OpenRouter | `GET https://openrouter.ai/api/v1/models` | Public catalogue. Unauthenticated. |
| OpenRouter | `GET /api/v1/models?category=embedding` | Same endpoint. Returned HTTP 400 — no such filter. |
| GitHub | `GET https://api.github.com/rate_limit` (unauthenticated) | Documented as not counting against any limit. |
| GitHub | `GET https://api.github.com/rate_limit` (with `GITHUB_TOKEN`) | Same. |
| Cohere | `GET https://api.cohere.com/v1/models?page_size=200` | Catalogue listing. No rerank, no inference. |
| Firecrawl | `GET https://api.firecrawl.dev/v2/team/credit-usage` | Usage read. Scrapes nothing. |
| Firecrawl | `GET https://api.firecrawl.dev/v2/team/token-usage` | Usage read. Scrapes nothing. |
| Pinecone | `list_indexes`, `describe_index`, `describe_index_stats` | Control-plane / metadata reads. |

I did **not** call `POST /api/v1/embeddings`, because that endpoint is billed.
The consequence is recorded honestly under *Unverified* below.

No key, key fragment, or key length appears in this document or in anything I
printed. The `.env`-vs-OS-environment comparison was done by SHA-256 digest,
and only the boolean result was displayed.

---

## Task 1 — Credentials

### The checks, and what each answer has to be

Every row is a check **to run**, not a balance to read off this page. The answers
are account state and are deliberately not published here.

| Service | Check | What you need to see | Why it matters |
| --- | --- | --- | --- |
| **OpenRouter** | `GET /api/v1/key` | HTTP 200, and a **non-null `limit`** | A `null` `limit` means the key has no spend cap at all. **See risk F** — this is the single check most worth acting on. Also confirm it is a normal inference key, not a provisioning key. |
| **Firecrawl** | `GET /v2/team/credit-usage`, `GET /v2/team/token-usage` | Enough credits for the run, and a period end that is not imminent | Sizing is under *Non-token costs*: one run's market branch is 5–10 scraped results. Compare that against your own balance and plan quota. |
| **Pinecone** | `describe_index` + `describe_index_stats` on `PINECONE_INDEX_NAME` | Status **Ready**; dimension equal to `EMBED_DIMENSIONS` (768); cosine metric | A dimension mismatch breaks every cache read and write. Note the vector count **before** the run so you can compare afterwards — see risk J. |
| **Cohere** | `GET /v1/models` | HTTP 200, and `RERANK_MODEL` present in the catalogue | `/v1/models` exposes no quota, so key validity is provable this way and remaining balance is not. |
| **GitHub token** | `GET /rate_limit` | HTTP 200, with headroom on `core`, `search` and `code_search` | The documented authenticated ceilings are 5,000/hr `core`, **30/min `search`**, 10/min `code_search`. See the regime note below. |

All five authenticated when this document was written. Re-run them: a key that
worked in August is not a key that works today.

### The GitHub regime the run would be in — answered

`tools/github_feasibility.py:304-306` selects the bucket by token presence:

```python
token = os.getenv("GITHUB_TOKEN") or None
headers = _headers(token)
bucket = _TOKEN_BUCKETS[bool(token)]
```

With `GITHUB_TOKEN` present and authenticating, **the run uses the authenticated
bucket: `VALIDATOR_GITHUB_RATE_LIMIT_AUTHED = 24` req/min.**
GitHub's documented authenticated search limit is **30 req/min**. The tool's own
bucket sits below GitHub's ceiling, so the token bucket binds first and there is
6 req/min of slack. PRD R-7's "10 req/min per IP" describes the *unauthenticated*
regime, which this run will not be in.

**The caveat that matters:** `_TOKEN_BUCKETS` is a module-level object, so the
bucket is shared across threads *within one process only*. Two processes (CLI +
service, or two benchmark shells) each get their own 24/min bucket — 48/min
against a real 30/min ceiling. See risk D.

### Environment shadowing — check it, because `.env` is not the only source

`agents/00-shared-config.md` documents a case where a credential exists **both**
in `.env` and as a machine-level OS variable, with different values. That is not
hypothetical: it has been observed here for `PINECONE_API_KEY` on a development
machine.

**The check.** For each credential the run uses, compare the `.env` value against
the OS environment — **by digest, never by printing.** A SHA-256 of each and a
boolean equality result is all you need, and all that should ever reach a
document. While you are there, confirm `OPENAI_API_KEY` is absent from *both*,
which is what makes an accidental OpenAI fallback impossible rather than merely
unlikely, and note whether `DATABASE_URL` is set — unset means the service falls
back to `output/validator-studio.db`.

**A mismatch is not automatically a defect.** `src/brief_crew/__init__.py:56`
runs `load_dotenv(_ENV_PATH, override=True)` at package import, deliberately and
with a docstring explaining exactly this scenario, so `.env` wins. The
consequence for verification: authenticate **after** importing `brief_crew`, so
you exercise the credential the run will actually use.

The residual risk is narrow but real: anything that touches a provider **without**
importing `brief_crew` first would silently use the OS credential instead. Nothing
on the validator path does that today.

Also worth checking: that no `.env` value carries stray whitespace or an embedded
CR. The file has CRLF line endings, and that has caught people out.

### Unverified, with the reason

| Item | Why unverified |
| --- | --- |
| **`EMBED_MODEL = "google/gemini-embedding-2"`** | OpenRouter's `/api/v1/models` lists **no embedding models at all** (0 of 396 ids contain "embed"), and `?category=embedding` returns HTTP 400. The only way to confirm the id and its price is to call `POST /api/v1/embeddings`, **which is billed**. I did not. Consequence: if this id is wrong, every cache lookup and every evidence write fails — see risk J for why that is non-fatal. |
| **Cohere quota / rate limit** | `/v1/models` authenticates but exposes no quota. Cohere has no free quota-introspection endpoint I could confirm. Key validity is proven; remaining balance is not. |
| **Firecrawl per-credit dollar cost** | PRD Q3 says this is unmeasured, and it still is. The credit *balance* is readable from the account; what a credit costs on this plan is not exposed anywhere I could read for free. I have not invented a number. |
| **Pinecone per-operation billing** | Not exposed by the control plane. Estimated from published serverless rates below, not measured. |

---

## Task 2 — The live path, traced by reading only

### Agent → model map

All six models are set **in Python, never in YAML**. `agents.yaml` contains no
`llm:` or `function_calling_llm:` key for any agent, so nothing overrides.

| Agent | Constant | Where | Tools |
| --- | --- | --- | --- |
| Scoper | `ESCALATION_MODEL` | `validator_crew.py:146` | none |
| Market Analyst | `CHEAP_MODEL` | `validator_crew.py:179` | Firecrawl |
| Sentiment Analyst | `CHEAP_MODEL` | `validator_crew.py:214` | HN Algolia |
| Feasibility Analyst | `CHEAP_MODEL` | `validator_crew.py:251` | GitHub |
| **Synthesist** | `ESCALATION_MODEL` + explicit `LLM(...)` | `validator_crew.py:298-308` | none |
| Reporter | `ESCALATION_MODEL` | `validator_crew.py:346` | none |

The Synthesist's explicit construction, verbatim:

```python
llm=LLM(
    model=ESCALATION_MODEL,
    additional_params=openrouter_reasoning_params(
        VALIDATOR_SYNTHESIST_REASONING_EFFORT
    ),
),
```

`VALIDATOR_SYNTHESIST_REASONING_EFFORT = "high"`. It resolves to
`ESCALATION_MODEL` — correct — but note it is the **only** agent whose LLM is not
a bare `LLM(model=CONSTANT)`, and it is the dominant cost line (Task 3).

**Three further LLM callers that are not in that table:**

1. **Both human gates.** `validator_flow.py:417` and `:519` pass
   `llm=CHEAP_MODEL` to `@human_feedback(...)`. Cheap, but real.
2. **The citation guardrail.** `reporting_task` carries `CITATION_GUARDRAIL`, a
   **string** guardrail. CrewAI's `LLMGuardrail` builds a throwaway
   `Agent(role="Guardrail Agent")` and kickoffs it — one extra LLM call per
   report attempt, pass or fail.
3. **Embeddings.** `EMBED_MODEL` is billed to `OPENROUTER_API_KEY` and carries no
   `openrouter/` prefix and no safety check.

I chased down (2) specifically, because a guardrail agent that defaulted to
OpenAI would kill the run at the last step with no `OPENAI_API_KEY` present.
`crewai/task.py:406` settles it:

```python
LLMGuardrail(description=self.guardrail, llm=self.agent.llm)
```

It **inherits the Reporter's LLM**, so it runs on `ESCALATION_MODEL`. No OpenAI
fallback. Good news for correctness, but it is an escalation-tier call.

### The startup assertion does not cover what its name implies

`service/app.py:128-148`. Two findings, both material:

**1. It never inspects a resolved LLM.** It checks the two module constants'
prefix, then text-scans `crews/*/config/agents.yaml` for `llm:` /
`function_calling_llm:`. No `Agent` is instantiated. **It would not catch a
hardcoded non-OpenRouter model on the Synthesist's explicit `LLM(...)`** — that is
exactly the hole worth knowing about. The YAML half is currently vacuous (no
validator agent has an `llm:` key) and would in any case validate a string the
Python `llm=` argument overrides.

**2. It runs on the service path only.** The sole production call site is
`app.py:162`, inside `create_app`. `validator_flow.py` never imports it.
**An operator running the CLI gets zero provider safety checking.**

Neither is a live defect *today* — I verified by reading that all six agents
resolve to the two constants, both `openrouter/`-prefixed. But the guarantee
rests on inspection, not on an assertion that will fire if someone edits
`validator_crew.py`.

### No test double can leak into the live path

`ValidatorCrewFactories` is a `frozen=True` dataclass whose field defaults are
module-level functions returning real crews (`validator_flow.py:91-128`). The
`--resume` path (`:727`) passes no factories and falls to that default.

**There is no environment variable anywhere in `src/` that flips synthetic mode.**
Synthetic runners are reachable only through an explicit Python keyword argument
(`create_app(synthetic=True)`), and `serve()` calls `create_app` as a uvicorn
factory with no arguments. The CLI has no synthetic option at all. The only
spend-confirmation gate in the codebase is `bench_fanout.py`'s `--live` + `--yes`.

Practical reading: **every path an operator can invoke is live.** There is no
dry-run.

### Spend bounds that exist

Set on agents in `agents.yaml`; nothing at crew level.

| Agent | `max_iter` | `max_rpm` | `max_execution_time` |
| --- | --- | --- | --- |
| scoper | 3 | — | 120 s |
| market_analyst | **12** | 6 | **600 s** |
| sentiment_analyst | 8 | 10 | 240 s |
| feasibility_analyst | 8 | 4 | 240 s |
| synthesist | 6 | — | 300 s |
| reporter | 8 | — | 300 s |

Worst case 45 agent iterations per run, up to 17 of them on `ESCALATION_MODEL`,
before guardrail retries. `max_rpm` throttles rate, it does not cap spend.
`_single_agent_crew` sets no `max_rpm`, no budget, no cache. **No
`guardrail_max_retries` is set on any validator task**, so all six inherit
CrewAI's default of 3 → up to 4 attempts, each re-running the whole task.

### Model and price drift — checked against the live catalogue

**No drift. Both models exist and every price in `config.py` matches what
OpenRouter advertises right now.**

> **⚠️ This check is dated 2026-08-29, and is deliberately NOT rewritten.** The
> table below records what the live catalogue said on that day, against the
> constants as they stood then. `ESCALATION_MODEL` has since moved
> `gemini-3.7-flash` → **`gemini-3.8-flash`** (`f19a2c6`, 2026-09-04, same
> $0.75 / $3.75), and `CHEAP_MODEL` has moved as well. The figures are left
> verbatim because a measurement of `gemini-3.7-flash` remains a true
> measurement of `gemini-3.7-flash`; renaming the model inside one would
> fabricate a check nobody ran. **Re-run the check, do not read it.** The same
> applies to the `Gemini 3.7 Flash` reasoning-token estimate further down under
> *Where the uncertainty actually is*.

| | `CHEAP_MODEL` | `ESCALATION_MODEL` |
| --- | --- | --- |
| Config id | `openrouter/z-ai/glm-5.3-flash` | `openrouter/google/gemini-3.7-flash` |
| In catalogue | Yes — "Z.ai: GLM 5.3 Flash" | Yes — "Google: Gemini 3.7 Flash" |
| Prompt, live vs config | $0.0750/M vs $0.0750/M — **match** | $0.7500/M vs $0.7500/M — **match** |
| Completion, live vs config | $0.2500/M vs $0.2500/M — **match** | $3.7500/M vs $3.7500/M — **match** |
| Context / max out | 1,310,720 / 131,072 | 1,048,576 / 65,536 |
| `reasoning` supported | Yes | Yes |

Cross-check: `output/last_run.json` records `cost_usd_upper_bound` =
0.19464675 for 109,104 prompt + 30,085 completion tokens. That is *exactly*
`109104×0.75/1e6 + 30085×3.75/1e6`. The price table is genuinely the one the
code uses, and it is correct.

**Three price components the catalogue charges that `PRICES` does not model:**

| Component | Live rate | Direction of error |
| --- | --- | --- |
| `internal_reasoning` (escalation) | $3.75/M — same as completion | **None, if OpenRouter reports reasoning tokens inside `completion_tokens`.** If it reports them separately, every Synthesist cost figure is **understated**. Unverified. |
| `input_cache_read` | $0.015/M cheap, $0.075/M escalation | System **over**-states cost. Safe direction. |
| `web_search` (escalation) | $0.014/call | Not used — no agent enables web search. |

The reasoning-token accounting is the one worth watching, because the Synthesist
runs at `effort: "high"` and is the largest line item.

---

## Task 3 — Cost estimate, with working

### Method and anchors

Bottom-up, per agent, using `PRICES` (verified above) and the actual prompt sizes
measured from the YAML:

| Task | chars | ≈ tokens |
| --- | --- | --- |
| `scoping_task` | 690 | 181 |
| `market_task` | 1,772 | 466 |
| `sentiment_task` | 1,186 | 312 |
| `feasibility_task` | 1,510 | 397 |
| **`synthesis_task`** | 8,635 | **2,272** |
| `reporting_task` | 2,504 | 658 |

Agent role/goal/backstory blocks are 104–127 tokens each. To these I add
CrewAI's ReAct/format scaffolding and output-schema instructions
(~1,200–2,000 tokens per call), and for tool agents the accumulating scratchpad.

**The one real observation available** is `output/last_run.json` — a genuine
Brief Crew `cache_miss` run: 13 requests, 109,104 prompt + 30,085 completion =
139,189 tokens. That is 3 agents, 2 with tools, and it gives a credible
per-request scale (~8.4k prompt/request once a scrape lands in context).
`output/perf/*.json` contains **no** token data — those runs were synthetic.
After a live run, reconcile the estimate below against your own OpenRouter
activity page; the useful comparison is *that run's* reported usage against this
table, not an account total.

### One gated run — central estimate

| Agent | Model | Prompt tok | Completion tok | Cost |
| --- | --- | --- | --- | --- |
| Scoper | ESC | ~1,900 | ~400 | **$0.0029** |
| Market Analyst | CHEAP | ~47,000 | ~2,500 | **$0.0041** |
| Sentiment Analyst | CHEAP | ~30,000 | ~2,000 | **$0.0028** |
| Feasibility Analyst | CHEAP | ~12,000 | ~1,500 | **$0.0013** |
| **Synthesist** | ESC + reasoning | ~10,200 | ~2,000 visible **+ ~5,000 reasoning** | **$0.0339** |
| Reporter | ESC | ~5,300 | ~3,000 | $0.0152 |
| Citation guardrail | ESC | ~4,700 | ~200 | $0.0043 |
| 2 × gate LLM | CHEAP | ~1,000 ea | ~200 ea | $0.0003 |
| Embeddings | unknown | ~30,000 embedded | — | ~$0.002 *(unverified rate)* |
| **Total** | | | | **≈ $0.065** |

Worked example for the dominant line — the Synthesist:
`10,200 × 0.75/1e6 = $0.00765` prompt, `7,000 × 3.75/1e6 = $0.02625` completion
(visible + reasoning), total **$0.0339**.

**The shape of the bill is the useful finding: roughly 80% of it is the
Synthesist and the Reporter.** All three research branches together are about
$0.008 — cost noise. Optimising Firecrawl or HN volume would save almost nothing;
the escalation tier is where the money is.

**Range: $0.03 – $0.15** for a clean run.
**With one revise cycle at each gate, or a couple of guardrail retries: up to
~$0.35.**
**Absolute worst case** (45 iterations, 4 attempts on synthesis and report):
**~$0.60–0.80.** Bounded — but see risk F, since nothing enforces that bound.

### Headless `--no-gates` run

Financially **the same, ≈ $0.065**. It runs the identical six agents; it only
removes the pauses and the possibility of a `revise` cycle, which makes it the
*cheaper-in-expectation* option because a revise re-runs an escalation agent.
The difference is operational, not monetary.

### `bench_fanout.py --live --yes --runs 5`

The script's own banner computes `args.runs * 2` — **10 full validator runs**
(5 parallel + 5 sequential), `no_gates=True`, warm-up 0 for live.

**≈ $0.65 central. Range $0.30 – $1.50. Worst case with retries ~$4.**

It also runs `isolate_cache=not args.live`, so live benchmark runs write into
the **real** Pinecone namespace, and multiplies Firecrawl/GitHub/HN load by 10.

### Non-token costs

**Firecrawl.** `market_research.py:173-177` calls
`Firecrawl(...).search(query, limit=limit, scrape_options=ScrapeOptions(formats=["markdown"]))`
with `limit` defaulting to 5 (schema max 10). Billing is per result **fetched and
scraped**. **PRD Q3 says the per-credit economics are unmeasured, and they still
are — I am not inventing a rate.** What is safe to state is the *shape*: at
roughly 1 credit per scraped result, one run's market branch costs **5–10
credits**; even at 5 credits per result it is ~25–50, and the 10-run benchmark is
ten times that. Check those figures against your own balance before running — on
a topped-up account they are noise, against a bare plan quota they are not. The
question no balance answers is the dollar value of a credit.

**Cohere rerank.** `RETRIEVE_CANDIDATES = 20` documents per call, one call per
cache lookup — market is always on, feasibility only with the flag. So **1–2
rerank calls per run**. Cohere bills a "search unit" as one query against up to
100 documents, so 20 documents is 1 unit. At published rerank pricing (~$2 per
1,000 search units) that is **~$0.002–0.004 per run**, ~$0.04 for the benchmark.
In practice likely **$0** on a cold index, because retrieval returns too little
to rerank.

**Pinecone.** Serverless, on-demand. Per run: 1–2 queries plus upserts for
indexed evidence (order 20–60 vectors). At published serverless rates
(~$0.33/M read units, ~$2/M write units, ~$0.33/GB-month storage) this is
**effectively $0.00 per run** — several orders of magnitude below billing
granularity. Storage of a few hundred small vectors is likewise immaterial.

### Where the uncertainty actually is, ranked

1. **Synthesist reasoning-token volume.** ~50% of the bill, and I have **zero**
   observations of it. `effort: "high"` on Gemini 3.7 Flash could plausibly be
   2,000 or 20,000 reasoning tokens. This single unknown sets the width of the
   whole range. Compounded by uncertainty (above) over whether OpenRouter reports
   those tokens inside `completion_tokens` at all — if not, the system's own cost
   telemetry will understate the true bill.
2. **Guardrail retries.** The rubric guardrail (0.85 anchor overlap + evidence
   support) and the two report guardrails have **never run against a real
   model**. Each rejection re-runs the most expensive agent. Up to 4 attempts.
3. **Firecrawl scraped page size** — drives market-branch prompt volume, but at
   cheap-tier pricing it barely moves the total. Low-impact uncertainty.
4. **Embedding rate** — unverifiable for free; small absolute contribution.

Assumption stated plainly: I assumed ~3 LLM calls per tool-using agent (one tool
call plus a final answer, with one re-plan). If a branch actually exhausts
`max_iter` (12 for market), that branch's cost rises ~4× — to about $0.016, which
still would not change the total materially.

---

## Task 4 — What would waste the money, and the pre-checks

Ordered by how much money each would burn before it bites.

### A. BLOCKER — `validate.exe` and `serve.exe` do not exist

The command documented in `CLAUDE.md` will not run:

```
.venv/Scripts/validate.exe   ->  No such file or directory
.venv/Scripts/serve.exe      ->  No such file or directory
```

`pyproject.toml` declares five console scripts, but the **installed** dist-info
records only three:

```
[console_scripts]
kickoff = brief_crew.main:kickoff
plot = brief_crew.main:plot
run_crew = brief_crew.main:run_crew
```

`validate` and `serve` were added to `pyproject.toml` after the editable install
and the venv was never re-synced. `run_crew.exe`, `kickoff.exe`, `plot.exe` are
all present; the two Validator Studio entry points are not.

This costs nothing — it fails instantly — but it will be the first thing the
operator hits, and the documented command is wrong. **Fix before the run** (free):

```powershell
.\.venv\Scripts\python.exe -m uv pip install -e .
```

Or bypass it entirely with the module form, which I verified works:

```powershell
.\.venv\Scripts\python.exe -m brief_crew.validator_flow --help
```

### B. Resume is CWD-keyed — get this wrong and the scope spend is gone

The gated CLI run is **three separate process invocations**, and pending flow
state is stored by CrewAI at:

```python
def get_project_directory_name() -> str:
    return os.environ.get("CREWAI_STORAGE_DIR", Path.cwd().name)
```

→ `C:\Users\<you>\AppData\Local\CrewAI\MultiAgentSystem`, derived from
**`Path.cwd().name`**. `CREWAI_STORAGE_DIR` is unset.

If the kickoff runs from `D:\MultiAgentSystem` and the resume runs from anywhere
whose directory basename differs, `from_pending(flow_id)` looks in a different
store and cannot find the gate. The Scoper (escalation tier) has already been
paid for at that point.

`OUTPUT_PATH = Path("output") / "validation.md"` is likewise **CWD-relative**.

**Pre-check: run all three invocations from `D:\MultiAgentSystem`.** Nothing
enforces it.

### C. The `RecursionError` in `Flow.resume()` — and resume is used twice

`CLAUDE.md` remaining-work item **9** (it was renumbered; the brief called it 13).
Seen once in ~6 gate-probe runs, never reproduced in a 10-round stress loop. It
is in `crewai`, not this repo.

A gated run calls `resume()` **twice**. A failure at the *verdict* gate means
scope + all three branches + the Synthesist are already sunk — the most expensive
possible moment.

I could not determine by reading whether re-issuing a failed resume continues
from the gate or re-runs completed branches. **The flow state is durable, so a
retry is possible; whether it is free is unknown.** I am flagging that as an
unknown rather than guessing.

**Recommendation: make the first paid run `--no-gates`.** It exercises all six
agents, all three tools, both guardrail sets and the report write for the same
money, while touching `resume()` zero times. Do the gated run second, once the
pipeline is known to work end to end.

### D. `RUN_CONCURRENCY` and the shared GitHub bucket

`RUN_CONCURRENCY` defaults to `1` (`config.py:484`), so the service executes one
paid run at a time. That is a safety feature — leave it alone.

The real hazard is **cross-process**: `_TOKEN_BUCKETS` is module-level, so each
process gets its own 24 req/min allowance against GitHub's single 30 req/min
ceiling for this token. **Do not run the CLI and the service at the same time,
and do not run two benchmark shells.** The symptom would be 403/429s on the
feasibility branch — which the tool reports honestly as `rate_limited`, producing
a *worthless but fully paid-for* verdict with F and X scored at the level-1
"evidence does not reach this question" anchor.

### E. Output overwrite

`persist()` does an unconditional `write_text`, so **any later run silently
overwrites `output/validation.md`.** Check whether the file already exists and
copy it before re-running. The benchmark is fine —
it writes to `output/perf/runs/<arm>-NN-validation.md`.

### F. Nothing in this repository bounds total spend

Not `config.py`, not CrewAI, not the Flow. `max_rpm` throttles rate and `max_iter`
bounds one agent's loop; neither is a budget. The only thing that can cap the bill
is a **credit limit on the OpenRouter key itself**, and that lives in the provider
dashboard, not in code.

**The check: `GET /api/v1/key` and read `limit` / `limit_remaining`. A `null`
`limit` means the key is uncapped.** The estimates above say a runaway is unlikely
to exceed ~$1, but nothing *enforces* that.

**This is the highest-value pre-check and it is free:** set a credit limit on the
key in the OpenRouter dashboard before the run. Even a $5 cap converts an
unbounded tail risk into a bounded one. Do it before deploying or publishing
anything that can trigger a run on that key.

### G. Guardrail exhaustion is fatal and lands late

No validator task sets `guardrail_max_retries`, so all six inherit CrewAI's
default of 3 (4 attempts). On exhaustion `Task._invoke_guardrail_function` raises
a plain `Exception` and, under `Process.sequential`, the run dies — **nothing is
written**.

The rubric guardrail and the two report guardrails have never been exercised
against a real model. **This is the single most likely way a first live run dies
having spent nearly everything.** The report step is last, so a citation-guardrail
failure burns 100% of the run's cost for zero output.

Mitigation: watch the console for guardrail rejection messages (`verbose=True`
is on everywhere) and be prepared to accept that run 1 may be a diagnostic rather
than a deliverable. Budget for two runs.

### H. Human gates: expiry is gentler than it looks

`VALIDATOR_GATE_TIMEOUT_SECONDS = 1800`. Per `config.py`'s own F03 note, an
unanswered gate past that is **marked `expired` and a frame is pushed — the run
is NOT failed and NOT auto-answered. It stays resumable, so a late reply still
resumes it.**

So: on the **CLI** path the process *exits* at each gate, so there is no
wall-clock pressure at all — pending state is durable and a resume hours later is
fine. On the **service/UI** path, answer within 30 minutes to avoid the `expired`
marking, but a late reply still works.

A person does need to be present for a gated run — just not under a 30-minute
guillotine.

### I. Traces are currently OFF

Trace consent is recorded per machine in
`C:\Users\<you>\AppData\Local\CrewAI\MultiAgentSystem\.crewai_user.json` as
`trace_consent`, and it is off unless you turned it on. Check it, and if you want
the trace run `crewai traces enable` **before** the run.

Per `CLAUDE.md`: a trace can contain prompts, task inputs/outputs, tool arguments
and results, and model responses. For this workflow that specifically includes
the idea text and **scraped third-party page content** from Firecrawl. Confirm
no secrets or personal data were processed before sharing a trace URL.

### J. A cold cache contributes nothing — and a broken one looks identical

Read `describe_index_stats` before the run. On a cold or near-empty index the
market cache lookup returns essentially nothing. That is **not** a failure:
`validator_flow.py:607-615` and `:624-633`
wrap both `_cached_evidence` and `_index_evidence` in bare
`except Exception: return []` / `pass`. Cache and embedding failures are
swallowed silently and the branch proceeds on live research.

Two consequences: (1) an empty cache block in the output is expected on run 1,
not a bug; (2) **if `EMBED_MODEL` is wrong** (the unverified item from Task 1),
you will never see an error — it will just silently never cache. Read
`describe_index_stats` again after the run: if the vector count has not grown
against the figure you noted beforehand, the embedding path is broken.

### K. Branch failure produces a confident, worthless verdict

Firecrawl and HN are the branches most likely to return `empty` or
`rate_limited`. The guardrails handle that honestly, but the *rubric* then scores
the affected dimension at the level-1 anchor. A run where sentiment came back
empty yields a verdict that measures the tooling, not the idea.

**Pre-check on the output before believing it:** confirm each branch's envelope
`status` is `ok`, not `empty` / `failed` / `rate_limited`.

### L. Note on rubric review (not a technical risk)

`CLAUDE.md` remaining-work item 5 and the "Recommended Next Sequence" both put
*read the five rubric ladders in `config.py`* **before** the paid run. The
anchors are binding at 0.85 overlap, they are a derivation rather than a spec,
and they have been audited but never read by a human. That is a decision, not
work to schedule — but the money is spent scoring against them.

### Pre-flight checklist

- [ ] Confirm `limit` is non-null on the OpenRouter key — and set one if it is not (risk F). Free, highest value
- [ ] `uv pip install -e .` so `validate`/`serve` exist, or use the module form (A)
- [ ] Read the five rubric ladders in `config.py` (L)
- [ ] `cd D:\MultiAgentSystem` and stay there for all invocations (B)
- [ ] Confirm nothing else is running that touches GitHub (D)
- [ ] `crewai traces enable` if a trace is wanted (I)
- [ ] Decide: `--no-gates` first (recommended, avoids `resume()` entirely — C)
- [ ] Back up `output/validation.md` if it already exists — the next run overwrites it (E)
- [ ] Record the index vector count before the run (J)
- [ ] After the run: check branch statuses (K), and whether the vector count grew (J)

---

## Task 5 — The exact commands

All three assume `D:\MultiAgentSystem` as the working directory. Both forms are
given: the `python -m` form works **today**; the `.exe` form works only after the
editable install is refreshed (risk A).

### Option 1 — Headless, `--no-gates`  ·  ≈ $0.065  ·  **recommended first**

```powershell
cd D:\MultiAgentSystem
.\.venv\Scripts\python.exe -m brief_crew.validator_flow --idea "A scheduling assistant for clinics" --no-gates 2>&1 | Tee-Object output\validator-live-01.log
```

After `uv pip install -e .`, equivalently:

```powershell
.\.venv\Scripts\validate.exe --idea "A scheduling assistant for clinics" --no-gates
```

**What the operator sees.** Verbose CrewAI output for all six agents, prefixed
per branch (`[market]`, `[sentiment]`, `[feasibility]`) while the three run
concurrently. Then the final `markdown_body` printed to stdout.

**What the operator does.** Nothing — it is unattended. Both gates auto-approve.
Expect several minutes, dominated by Firecrawl scrapes (`max_execution_time` on
the market analyst is 600 s).

**Afterwards.** Report at `output\validation.md`. Verify branch statuses and
citation closure before trusting the verdict.

### Option 2 — Gated, both human gates  ·  ≈ $0.065, up to ~$0.35 with revisions

**Three invocations.** The process exits at each gate.

**Step 1 — kick off, pause at the scope gate:**

```powershell
cd D:\MultiAgentSystem
.\.venv\Scripts\python.exe -m brief_crew.validator_flow --idea "A scheduling assistant for clinics"
```

Prints, and exits:

```json
{
  "status": "pending_human_feedback",
  "flow_id": "...",
  "gate": "confirm_scope",
  "message": "Confirm the parsed scope. Reply with JSON using decision=approve, or decision=revise plus feedback and an optional edited scope object.",
  "output": "{ ...the ScopedIdea JSON to review... }"
}
```

**The operator must copy the `flow_id`.** Read the `output` block — this is the
research contract all three branches will spend money against.

**Step 2 — approve the scope, run the branches, pause at the verdict gate:**

```powershell
.\.venv\Scripts\python.exe -m brief_crew.validator_flow --resume <FLOW_ID> --feedback '{\"decision\": \"approve\"}'
```

To send it back instead:

```powershell
.\.venv\Scripts\python.exe -m brief_crew.validator_flow --resume <FLOW_ID> --feedback '{\"decision\": \"revise\", \"feedback\": \"Narrow the v1 to appointment reminders only.\"}'
```

A `revise` re-runs the escalation-tier Scoper and returns to this same gate.
There is no cap on revise cycles.

`--feedback` defaults to `{"decision": "approve"}`, so it may be omitted for an
approval — but pass it explicitly; approving a gate by omission is a bad habit
when each one costs money.

This step prints a second `pending_human_feedback` block with
`"gate": "review_verdict"` and the scored `Verdict` JSON, then exits.

**Step 3 — approve the verdict, write the report:**

```powershell
.\.venv\Scripts\python.exe -m brief_crew.validator_flow --resume <FLOW_ID> --feedback '{\"decision\": \"approve\"}'
```

A `revise` here re-runs the Synthesist at `reasoning: high` — the most expensive
single agent in the system. The `flow_id` is the same throughout.

Note that at the **verdict** gate the service's UI treats every `Verdict` field as
read-only `derived`; the operator's only lever is `decision=revise` plus feedback.
The CLI accepts an edited object, but the schema recomputes the arithmetic and
the guardrails re-bind the rest, so the practical lever is the same.

**Afterwards.** Report at `output\validation.md`.

### Option 3 — Live benchmark  ·  **10 full runs**  ·  ≈ $0.65 (range $0.30–$1.50)

```powershell
cd D:\MultiAgentSystem
.\.venv\Scripts\python.exe scripts\bench_fanout.py --live --yes --runs 5
```

`--yes` skips the interactive confirmation. **Without `--yes` it prompts and the
operator must type `LIVE`.** Consider dropping `--yes` and typing it — the banner
states the cost in runs before anything starts.

**What the operator sees.** Interleaved arms so machine drift cannot favour one:

```
  parallel   #0    123.456s  ...
  sequential #0    301.789s  ...
```

**What the operator does.** Nothing — `no_gates=True` throughout.

**Afterwards.** JSON and text results in `output\perf\`; per-run reports in
`output\perf\runs\`. It answers PRD Q1: ≥1.8× fan-out speedup and peak RSS
< 400 MB.

**Run this last.** It is the most expensive option and it is only meaningful once
a single run is known to work.

---

## Bottom line

Every credential in the table authenticated when this was written. Both models
exist and **every price in `config.py` matched OpenRouter's live catalogue** —
the cost telemetry is sound. No test double can reach the live path. Credential
shadowing of the kind `agents/00-shared-config.md` warns about is real on at
least one machine here, but `override=True` already handles it.

Two things to settle before spending anything: **the console scripts may not be
installed** (the documented `validate.exe` command fails outright when the
editable install is stale), and **the OpenRouter key may have no spend cap**.
Both are free to check and take a minute.

One recommendation worth the emphasis: **make the first paid run `--no-gates`.**
Same six agents, same tools, same guardrails, same money — and it never touches
the `Flow.resume()` path that carries the one known intermittent crash.

> **If the paid run is through the DEPLOYED SERVICE rather than this CLI, one
> more thing must be true first** (added 2026-09-04). The CLI path
> (`python -m brief_crew.validator_flow`) never builds the FastAPI app, so
> nothing here changes. The service path does, and since plan 01 `create_app`
> **refuses to start** when `AUTH_BASE_URL` is set and `CREDENTIALS_MASTER_KEY`
> is empty — which is exactly the state `render.yaml` described until
> 2026-09-04. Measured, with the reproduction, in `CLAUDE.md` remaining-work
> item 46; the runbook entry is step 4 of [`deploying.md`](deploying.md). It
> costs nothing to check and it is the difference between a paid run and a
> service that never comes up.
>
> The go-live checklist at the head of `deploying.md` is the fuller version of
> this paragraph, and it names three other things that are not ready.
