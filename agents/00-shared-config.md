# 00 · Shared Configuration & Tech Stack

Everything in `01`–`08`, and `workflow.md`, assumes this file.

**Verification status.** Every version, price, parameter and API shape below was
confirmed by installing and executing the real thing on 2026-08-29 — not from
documentation. The Pinecone index and Postgres database referenced here exist;
the retrieval path was smoke-tested end to end. Documentation conflicts are
flagged inline, in §9.

> ✅ **The implementation now exists** (2026-08-29). `src/brief_crew/` is the
> code these specs describe; §11 maps every section to the file that implements
> it. Re-verified against a live install on the same date:
>
> | Claim | Status |
> |---|---|
> | `crewai` / `crewai-tools` **1.15.18** is current on PyPI | ✅ confirmed — these are the newest releases, not merely pinned |
> | OpenRouter is a **native** provider, no `litellm` | ✅ `LLM(model="openrouter/...")` resolves to `crewai.llms.providers.openai_compatible.completion`, `base_url=https://openrouter.ai/api/v1` |
> | `reasoning_effort` is accepted on `LLM` | ⚠️ accepted, then **silently dropped** for every non-o1 model — see §3 |
> | Every `Agent` / `Task` field §8 relies on exists | ✅ all 16 present, including `Task.guardrails` (plural) and `Agent.mcps` |
> | Pinecone unreachable natively | ✅ `SupportedProvider = Literal['chromadb', 'qdrant']` |
> | Embeddings honour `dimensions=768` when called directly | ✅ live call returned 768-dim vectors |
> | Cohere `rerank-v4.0-fast`, Firecrawl search, both LLM tiers | ✅ all answered live |
>
> **One correction to the environment, not to this file:** see the `.env`
> shadowing trap added to §2 below. It is the only setup problem found.

## Two tracks — know which one you are building

The word "Track" appears throughout these specs. It means one of exactly two
things:

| | **Track A — the classroom crew** | **Track B — the hosted service** |
|---|---|---|
| What it is | Slides 45–48's build: three agents, three tasks, one `Crew` | Track A plus a Pinecone warm cache, Postgres run history, and Render hosting |
| Orchestration | `Process.sequential` | `crewai.flow` with a deterministic `@router` |
| Retrieval | the Researcher's own `retrieve_and_rerank` tool | the Flow's `retrieve_cached` `@start` step, *before* any agent runs |
| Researcher tools | 3 — but **2 until `06`'s retrieval tool is built**, and step 0 of the task comes out until then (see README's Track A block) | 2 — see `01-researcher.md` §"Which track are you building?" |
| Infrastructure | none — runs on a laptop | Pinecone · Cohere · Render Postgres · Render web |
| Where specified | slides 45–48, `01`–`03`, `workflow.md` §5a | this file, `06`, `07`, `08`, `workflow.md` §5b |

**Build Track A first and get it running end to end.** Every stretch in this
repository — the MCP swap (`01`), the Manager comparison (`04`), the evaluator
gate (`05`) — presupposes a working sequential crew. Slide 52's half-way
checkpoint is *"a crew of three agents that runs end to end"*, not a Flow.

Sections below are Track B unless marked otherwise; where Track A differs, it is
called out inline.

---

## 0. Why a crew at all

Read this before building anything. Slide 55 is blunt: *"Most things you'll want
to build as a crew are cheaper, faster, and more reliable as one agent."* Slide
33 and slide 43 both quote Anthropic: *"Find the simplest solution possible, and
only increase complexity when needed."*

Slide 09 names five ceilings that justify going multi-agent. This build clears
**two of five**:

| # | Ceiling (slide 09) | Cleared? | Why |
|---|---|---|---|
| 1 | Context overload | **Partly** | Scraped markdown is bulky, but one topic is one domain. |
| 2 | Tool overload | **No** | Three tools, all on one agent. The deck's warning starts at 20+. |
| 3 | Cognitive scatter | **Yes** | *"Research AND analyse AND write AND critique → mediocre at each."* Four verbs, four owners. This is the real justification. |
| 4 | Speed | **No** | The pipeline is strictly serial; every stage consumes its predecessor's whole output. And §2's ~210 MB footprint caps a `starter` instance at one concurrent run anyway. |
| 5 | Specialisation | **Yes** | Two model tiers, deliberately split (§3). |

Against slide 56's GO/STAY test the honest reading is uncomfortable:

- ✅ *Genuinely different expertise domains* — arguable; see `02-analyst.md`'s
  closing argument, which contests it.
- ❌ *Real speed gain from parallel subtasks* — no. See `workflow.md` §8.
- ❌ *A security boundary* — no. All five credentials are process-wide readable
  by every agent.
- ✅ *Quality needs a separate critic* — yes, that is `05-evaluator.md`.
- ❌ *Single-agent tried and **measurably failed*** — **this has not been done.**
  There is no single-agent baseline anywhere in this repository.

That last line is the most important sentence in this file. Slide 55 predicts
your crew makes **~10 LLM calls** where one good agent makes one, and slides 55
and 65 both put the multi-agent premium at **3–10×**. Running that baseline is
the cheapest experiment available and the strongest evidence you can bring to
slide 53's *"whether you'd keep it"*. `workflow.md` §10 records it as a declared
gap rather than pretending otherwise.

Build the crew — it is the assignment. But build it knowing the case against it,
because that case is the graded question.

---

## 1. Tech stack

| Layer | Choice | Version / plan |
|---|---|---|
| Language | Python | **3.13** (`crewai` requires `>=3.10,<3.14`) |
| Env manager | **uv** | 0.7.19 — mandatory, see §2 |
| Framework | `crewai` | **1.15.18** |
| Tools | `crewai-tools` | **1.15.18** — strict lockstep |
| Web fetch | `firecrawl-py` | **4.40.0** |
| Vector store | `pinecone` | **9.1.0** (package is `pinecone`, *not* `pinecone-client`) |
| Rerank | `cohere` | latest |
| LLM + embeddings | **OpenRouter** — native provider | — |
| Database | **Render Postgres 18** | `basic_256mb` |
| Hosting | **Render** — web service + static site | `starter` / free |
| Orchestration | `crewai.flow` — `@start` / `@router` / `@listen` | ships in core |
| **Observability** | **CrewAI AMP tracing** + Postgres `run_metrics` | Free tier |

### Credentials — five secrets, all already provisioned (plus one injected)

| Variable | Serves |
|---|---|
| `OPENROUTER_API_KEY` | every LLM **and** all embeddings |
| `FIRECRAWL_API_KEY` | web search + scrape |
| `PINECONE_API_KEY` | vector store |
| `COHERE_API_KEY` | stage-2 reranking |
| `RENDER_API_KEY` | deployment / provisioning |
| `DATABASE_URL` | injected by Render at deploy time, not stored in `.env` |

Plus non-secret configuration variables. **`PINECONE_INDEX_NAME`** =
`agentic-crew-ai-index` is present in `.env` and set on the service. The hosted
service adds:

| Variable | Set where | Serves |
|---|---|---|
| `CORS_ALLOW_ORIGINS` | service only | comma-separated **origins** (scheme + host + optional port, **no trailing slash**) allowed to call `/api`. Default empty = no cross-origin caller. Invisible locally, because Vite proxies `/api` and `/ws` same-origin; mandatory in production, where the static site is a separate origin. A malformed value **stops startup** and names the corrected string. It does **not** govern `/ws` — browsers do not apply CORS to a WebSocket handshake. `07-deployment.md`. |
| `SYNTHETIC` | local only | `1` makes the `serve` console script build **no-cost doubles** instead of the paid crew runners. Never set it on a deployed service: it would return fabricated verdicts through a UI that gives no sign of it. |
| `HOST` / `PORT` | service | bind address; `serve` defaults to `127.0.0.1:8000`, which a PaaS proxy cannot reach. |
| `RUN_CONCURRENCY` | service | concurrent runs, default `1` — the memory ceiling on a 512 MB instance. |
| `RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS` | service | default `5.0` — how long a resubmission waits for a still-settling run future before refusing the caller. |
| `MAX_QUEUED_RUNS` | service | default `8` — runs queued or executing, across **every** caller, above which a new run gets `429`. This is the keyless cost bound; it cannot be rotated around. |
| `RUN_RATE_LIMIT_MAX_RUNS` | service | default `10` — per-client run-creation burst. **`0` disables the limiter**, the intended escape hatch for load testing a private deployment. |
| `RUN_RATE_LIMIT_WINDOW_SECONDS` | service | default `60.0` — the window that burst refills over. |
| `RUN_RATE_LIMIT_TRUST_FORWARDED_FOR` | service | default **on**. Key the limiter on the leftmost `X-Forwarded-For` entry. Required behind a PaaS proxy, where the socket peer is the proxy and every visitor would otherwise share one bucket. **Turn it off** wherever the service is reachable directly. |
| `EXPOSE_API_DOCS` | service | default **off**. Serves `/docs`, `/redoc` and `/openapi.json`, which are otherwise `404`. Forced on for a synthetic app. Obscurity, not a control — see §Admission control below. |
| `VALIDATOR_FEASIBILITY_CACHE_ENABLED` | either | default off — opts the feasibility branch into the warm cache as a GitHub rate-limit shock absorber. |
| `VALIDATOR_SEQUENTIAL_BRANCHES` | either | default off — withdraws the three-way fan-out to one-at-a-time without a code edit. |

Every variable in both tables above is read at **import time** in
`config.py`, except `SYNTHETIC`, `HOST`, `PORT` and `DATABASE_URL`, which
`service/app.py` reads. The numeric ones **stop startup** on a malformed value
rather than silently coercing it.

> ⚠️ **Do not add an admission knob to this table by inference.** The rest of
> the admission-control settings are deliberately **constants, not environment
> variables**, so changing one is a code edit and a commit rather than a
> dashboard field nobody remembers setting: `MAX_REQUEST_BODY_BYTES` (64 KiB),
> `MAX_RUN_INPUT_CHARS` (2000), `MAX_RUN_INPUT_KEYS` (16),
> `MAX_RUN_INPUT_BYTES` (8 KiB), `RUN_ADMISSION_RETRY_AFTER_SECONDS` (30),
> `RUN_RATE_LIMIT_MAX_CLIENTS` (4096) and `RUN_RATE_LIMIT_KEY_MAX_CHARS` (64).
>
> A line-based `grep` over `config.py` **undercounts** the real list, because
> two of the calls above wrap their name onto the next line. If you are
> regenerating this table, match across lines:
>
> ```bash
> grep -Pzo '(os\.getenv|_env_[a-z_]+)\(\s*"[A-Z_]+"' src/brief_crew/config.py \
>   | tr '\0' '\n' | grep -oE '"[A-Z_]+"' | sort -u
> ```
>
> That returns **eleven** names as of 2026-08-30. A `grep -oE` without `-Pzo`
> returns nine and silently drops `RUN_RATE_LIMIT_WINDOW_SECONDS` and
> `RUN_RATE_LIMIT_TRUST_FORWARDED_FOR` — which is how a previous revision of
> this table came to describe two live knobs as hard-coded constants.

**No new accounts are required.** In particular no Google key: `gemini-embedding-2`
is served through OpenRouter. No OpenAI key: `Crew.memory` stays `False`, so the
default OpenAI embedder is never constructed.

> ✅ **`.env` spelling: fixed.** Earlier revisions of this spec warned that `.env`
> read `FIRECRWALL_API_KEY`. As of 2026-08-29 the file reads `FIRECRAWL_API_KEY`,
> which is what every Firecrawl tool declares
> (`EnvVar("FIRECRAWL_API_KEY", required=True)`). No action needed — but the
> failure mode is worth remembering, because a misnamed key lets the tools
> construct fine and fail only at the first live call.
>
> `.env` also carries `PINECONE_INDEX_NAME=agentic-crew-ai-index`. It is
> configuration rather than a credential, so it is absent from the table above;
> the retrieval tool still requires it.

---

## 2. Environment setup

`crewai` pins `pydantic<2.13`; the machine's conda base has 2.13.2. An isolated
environment is mandatory, not advisory.

### ⚠️ `.env` is silently shadowed by the machine environment

**Found on this machine, 2026-08-29.** `PINECONE_API_KEY` exists as a
*machine-level environment variable* holding a **different value** from the one
in `.env`:

```
machine env : pcsk_<redacted-A>   (75 chars)
.env file   : pcsk_<redacted-B>   (75 chars)
```

`python-dotenv` does **not** override existing environment variables by default,
so `load_dotenv()` leaves the machine value in place and the project runs on a
credential the repository never declared.

Both keys currently authenticate to the same Pinecone account — they list the
same six indexes, `agentic-crew-ai-index` among them — so **nothing is broken
today**. That is precisely what makes it worth writing down: it works until the
machine-level key is rotated or revoked, and the failure then points at a `.env`
file that was correct the whole time. The same shadowing applies to any variable
someone has ever exported globally.

**The fix, implemented in `src/brief_crew/__init__.py`:**

```python
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if _ENV_PATH.is_file():
    load_dotenv(_ENV_PATH, override=True)
```

Two decisions in three lines. `override=True` makes what the repository declares
authoritative. Resolving the path from `__file__` rather than the CWD makes the
crew behave identically whether it is launched from the repo root, from `src/`,
or by uvicorn under Render — `find_dotenv()`'s default walk starts at the
*calling file*, which is why a script run from a temp directory sees no
credentials at all. On Render nothing is overridden, because `.env` is
gitignored and never reaches the image; secrets arrive as real environment
variables via `sync: false`.

> While confirming this the Pinecone index held **0 vectors**. It now holds
> **3**, written back by the first `crewai run`, and *cashless payments in
> Singapore* consequently routes `cache_hit`. Any other topic still misses until
> write-back has covered it — see the cost note in `README.md`.

### Two ways in: the CLI, or the venv directly

The CrewAI CLI is installed globally as a uv tool, so `crewai` resolves from any
directory:

```bash
uv tool install crewai     # -> crewai 1.15.18 on PATH
crewai install             # uv sync against pyproject + writes uv.lock
crewai run                 # runs the Flow — [tool.crewai] type = "flow"
```

⚠️ **`crewai install` is not additive.** It runs `uv sync`, which makes the venv
*exactly* match `pyproject.toml` — anything outside the default dependency set is
**uninstalled**. Here it correctly removed `fastapi`, `sqlalchemy`, `psycopg` and
`greenlet`, which live in the optional `service` extra. Put them back with
`uv pip install -e '.[service]'` when Track B deployment gets built.

It also writes **`uv.lock`**, which `07-deployment.md` requires at the repo root
because Render auto-detects it to pin the build.

Or set the environment up by hand, which is what the CLI is doing underneath:

```bash
uv venv --python 3.13 .venv
uv pip install 'crewai[tools]' firecrawl-py pinecone cohere \
               fastapi uvicorn sqlalchemy psycopg[binary]
```

- `crewai[tools]` pins `crewai-tools==1.15.18`.
- **`firecrawl-py` must be named explicitly** — `crewai[tools]` does not pull it.
- Expect ~150 packages. `chromadb`, `lancedb` and `onnxruntime` are
  **unconditional** dependencies with no slim extra to avoid them.

### Do NOT install `crewai[litellm]`

CrewAI's own 1.15.18 docs say OpenRouter "uses LiteLLM. Add it as a dependency."
**Stale.** Tested with `litellm` absent:

```
LLM(model="openrouter/z-ai/glm-5.3-flash")
  -> crewai.llms.providers.openai_compatible.completion.OpenAICompatibleCompletion
     base_url = https://openrouter.ai/api/v1     provider = openrouter
```

OpenRouter is a native provider. LiteLLM is a lazily-imported fallback for
providers *not* in `SUPPORTED_NATIVE_PROVIDERS`, and OpenRouter is in that list.

### Memory footprint — sizing input

Measured RSS in a real process:

| | RSS |
|---|---|
| baseline Python | 19.6 MB |
| `import crewai` | 152.3 MB |
| `+ crewai_tools` | 208.8 MB |
| + one Agent | 211.0 MB |

**~210 MB before any work**, from `chromadb`/`lancedb`/`onnxruntime` loading
whether used or not. On Render `starter` (512 MB) that leaves ~300 MB for
uvicorn and a live run. **One concurrent crew run per instance.** Concurrency
requires the `standard` plan (2 GB, $25/mo) or a separate worker.

### Observability

```dotenv
CREWAI_TRACING_ENABLED=true
```

Enables **CrewAI AMP tracing** — the chosen observability layer. The env var is
the correct switch rather than `tracing=True` in code, because it also bypasses a
first-run consent trap that would otherwise silently disable tracing forever in a
container. Full detail, including the Render authentication constraint, in
`08-observability.md`.

⚠️ `CREWAI_TRACING_ENABLED=false` does **not** disable tracing — there is no
branch returning `False` for it. Only `tracing=False` in code does.

### Optional

```dotenv
CREWAI_DISABLE_TELEMETRY=true
```

Anonymous usage pings, separate from AMP tracing. Accepts
`CREWAI_DISABLE_TELEMETRY`, `OTEL_SDK_DISABLED`, or `CREWAI_DISABLE_TRACKING`.
Does **not** silence ChromaDB's separate PostHog telemetry — `posthog` in the
tree belongs to ChromaDB, not CrewAI.

---

## 3. LLM — OpenRouter

OpenRouter is native, so configuration is **just the model string**. `base_url`,
API key and the ranking header all resolve automatically from
`OPENROUTER_API_KEY`.

```
model = openrouter/<vendor>/<model>
```

Resolution order: explicit argument → environment variable → built-in default.

- Base URL override: `OPENROUTER_BASE_URL` (**not** `OPENROUTER_API_BASE`).
- CrewAI sends `HTTP-Referer: https://crewai.com` on every call. Override via
  `default_headers={"HTTP-Referer": ..., "X-Title": ...}`.
- ⚠️ Use **`default_headers`**, never `extra_headers` — the latter appears in
  CrewAI's observability docs, exists on no model in 1.15.18, and is **silently
  discarded** by pydantic's `extra="ignore"`.

### Model assignment

Two tiers. Prices verified against the live catalogue, USD per million tokens,
**prompt / completion**.

| Role | Model | $/Mtok | Why |
|---|---|---|---|
| **Default (cheap tier)** | `openrouter/z-ai/glm-5.3-flash` | **0.075 / 0.250** | 1,310,720 context, supports `tools`. Cheapest capable tool-caller in the catalogue. |
| **Escalation** | `openrouter/google/gemini-3.7-flash` | 0.75 / 3.75 | 1,048,576 context. Ten times the *input* price, fifteen times the *output* price — use only where judgement genuinely lives. |

> ⚠️ **`glm-5.3-flash` reasons by default, and reasoning bills at the completion
> rate.** Measured on a one-word prompt: 68 of 71 completion tokens were
> reasoning. Setting the effort to `"minimal"` dropped it to 3 tokens and 0
> reasoning — an **8.8× cost reduction** on short mechanical calls.
>
> 🛑 **But `reasoning_effort=` on `LLM` does not reach OpenRouter.** Verified
> against the installed 1.15.18 wheel: `OpenAICompletion._prepare_completion_params`
> forwards it only under `if self.is_o1_model`, and `is_o1_model` is
> `"o1" in model.lower()`. Neither model here matches, so the value is accepted,
> stored on the object, and then dropped — no error, no warning. The saving
> below was never actually being collected.
>
> The route that works is OpenRouter's unified `reasoning` object, carried in
> `extra_body`:
>
> ```python
> LLM(model=CHEAP_MODEL,
>     additional_params={"extra_body": {"reasoning": {"effort": "minimal"}}})
> ```
>
> `config.py::openrouter_reasoning_params()` builds this. Do not pass a
> top-level `reasoning=` key: the OpenAI SDK's `chat.completions.create` has no
> `**kwargs` and would raise.
>
> | variant | completion | reasoning | cost |
> |---|---|---|---|
> | default | 71 | 68 | $1.92e-05 |
> | `reasoning_effort: "minimal"` | 3 | 0 | $2.18e-06 |
> | `reasoning.exclude: true` | 21 | 18 | $1.34e-05 |
>
> Note `reasoning.exclude` only *hides* reasoning — it is still generated and
> billed. It is not a cost control. Apply the `extra_body` form above to the
> Evaluator, and test it on the Researcher. Leave the Analyst reasoning.

Per agent:

| Agent | Model | Reasoning |
|---|---|---|
| Researcher | `glm-5.3-flash` | Longest tool loop, ingests raw scraped markdown. Wants cheap input tokens, not deep reasoning. Escalate if the tool loop thrashes. |
| Analyst | **`gemini-3.7-flash`** | The one real judgement step. Do not run this on the cheap tier. |
| Writer | `gemini-3.7-flash` | Prose quality is the visible output — but the task is heavily templated, making this the best A/B candidate for the cheap tier. |
| Manager *(retired, see `04`)* | `gemini-3.7-flash` | Kept for comparison only. |
| Evaluator | `glm-5.3-flash` | Mechanical rubric check. |

**Note the honest gap:** with Claude Sonnet 5 out of the roster, `gemini-3.7-flash`
is the ceiling. "If the brief reads thin, trade up" no longer has a destination
inside this two-tier stack. Widening it is a deliberate decision, not a default.

### Do not use `function_calling_llm`

```
deprecated="function_calling_llm is deprecated and will be removed in a future release."
```

Still functional in 1.15.18, but on the removal path.

---

## 4. Embeddings — OpenRouter

**Embedding models are absent from the default `/api/v1/models` response.** They
appear only with a filter:

```
GET https://openrouter.ai/api/v1/models?output_modalities=embeddings   # 34 models
```

This is worth knowing because the omission looks exactly like "OpenRouter does
not do embeddings", which is false.

| | |
|---|---|
| Endpoint | `POST https://openrouter.ai/api/v1/embeddings` (OpenAI-compatible) |
| Model | **`google/gemini-embedding-2`** |
| Price | $0.20/Mtok text |
| Max input | 8,192 tokens |
| Native dimension | 3072 |
| **Configured dimension** | **768** via the `dimensions` parameter |
| Batching | supported — pass a list to `input` |

**Why 768.** Gemini embeddings use Matryoshka representation learning, so
truncation is lossy but barely: MTEB scores 68.17 at 1536 versus **67.99 at 768**
— 0.18 points. Degradation only accelerates below 512. 768 cuts Pinecone storage
and query cost by half against 1536, and matches the 768-dim convention of a pre-existing index in the same account
index from the earlier RAG lectures (a *different* index from this project's
`agentic-crew-ai-index`). `gemini-embedding-2` **auto-normalizes** truncated vectors
(unlike `gemini-embedding-001`, which requires manual renormalization).

### ⚠️ Document/query asymmetry is your responsibility

`gemini-embedding-2` **removed** the structured `task_type` field that
`gemini-embedding-001` had. Google's own guidance is to put the task instruction
in the prompt text instead. So asymmetric embedding must be done by convention,
and the convention must match exactly on both sides or retrieval silently
degrades:

```
indexing : "Represent this document for retrieval: {chunk}"
querying : "Represent this query for retrieving relevant documents: {query}"
```

This is not an OpenRouter limitation — it is how the model works. But OpenRouter
gives you no field that would enforce it, so it lives in code review instead.

### ⚠️ Do NOT route embeddings through CrewAI's embedder

`chromadb/utils/embedding_functions/openai_embedding_function.py:123`:

```python
if self.dimensions is not None and "text-embedding-3" in self.model_name:
    embedding_params["dimensions"] = self.dimensions
```

`dimensions` is forwarded **only** when the model name contains the literal
`"text-embedding-3"`. `google/gemini-embedding-2` fails that test, so
`dimensions=768` would be silently dropped and you would get 3072-dim vectors
into a 768-dim index — no error, just a wall of failed upserts far from the
cause. Call the embeddings endpoint directly. See `06-retrieval-layer.md`.

---

## 5. Vector store — Pinecone

**Provisioned and live:**

| | |
|---|---|
| Index | `agentic-crew-ai-index` |
| Host | `<index>-<hash>.svc.<region>.pinecone.io` — the live host is in the Pinecone console. Kept out of this public repo: it embeds the project hash and control-plane shard, which are account-scoped and directly probeable. |
| Dimension | **768** |
| Metric | cosine |
| Spec | serverless · aws · **ap-southeast-1** (Singapore) |

Region deliberately matches the Render services so the whole system sits in one
geography.

**CrewAI cannot reach Pinecone natively.** Confirmed by source inspection:

```python
SupportedProvider = Literal["chromadb", "qdrant"]   # crewai/rag/config/optional_imports/types.py
```

and zero `pinecone` references anywhere in `crewai` or `crewai_tools`. Retrieval
therefore goes through a custom `BaseTool` calling the `pinecone` SDK directly —
specified in `06-retrieval-layer.md`. CrewAI's `embedder=` config is **off the
critical path** entirely; it configures only the Chroma-backed Knowledge/Memory
stores, which this design does not use.

---

## 6. Reranking — Cohere

| | |
|---|---|
| Endpoint | `POST https://api.cohere.com/v2/rerank` |
| Model | **`rerank-v4.0-fast`** — verified working |
| Billing unit | one query × up to 100 documents; documents over 500 tokens are split and each chunk counts |

Reranking runs **inside the retrieval tool**, not as an agent. It is a
cross-encoder scoring call with no reasoning content — wrapping it in an Agent
would buy a persona and an LLM call around a pure function.

**Measured on this index**, three documents against "cashless payments in
Singapore":

| | Pinecone cosine | Cohere rerank |
|---|---|---|
| PayNow doc | 0.8107 | **0.3717** |
| hawker QR doc | 0.7933 | 0.2184 |
| MRT doc | 0.7532 | 0.0906 |

Same ordering, but the spread widens from 0.06 to 0.28. That separation is what
makes a relevance threshold implementable — you cannot set a defensible
cache-hit cutoff on scores clustered within 0.06.

---

## 7. Database — Render Postgres

**Provisioned and live:**

| | |
|---|---|
| Name | `agentic-crew-ai-db` |
| ID | `dpg-<redacted>-a` — the live value is in the Render dashboard. Kept out of this public repo: it is the database's **internal hostname**, not a secret, but it is account-specific and of no use to anyone else. |
| Plan | `basic_256mb` — $6/mo + $0.30/GB |
| Version | PostgreSQL 18 · 1 GB disk |
| Region | singapore |

> Plan IDs in the Render **API** use underscores (`basic_256mb`); the docs show
> hyphens. The API form is what works.

**CrewAI has no native Postgres backend** for memory, knowledge, flow state or
checkpoints. Every subsystem exposes a pluggable seam (`StorageBackend` Protocol,
`BaseKnowledgeStorage` ABC, `FlowPersistence` ABC, plus `set_*_factory()`
registrars) but nothing ships that talks to Postgres.

So Postgres is owned by **application code via SQLAlchemy**, not forced through
CrewAI abstractions. It stores run history, generated briefs, and cache-hit/miss
telemetry. Schema in `07-deployment.md`.

With `memory=False` (the default), CrewAI writes nothing durable that matters,
so Render's ephemeral disk is a non-issue. If memory is ever enabled, set
`CREWAI_STORAGE_DIR` to an absolute path on a mounted disk — note the checkpoint
system ignores that variable and uses CWD-relative `./.checkpoints`.

---

## 8. Crew and Flow configuration

### Flow (Track B)

The one genuinely dynamic decision — cache hit versus miss — is resolved by a
deterministic `@router`, costing **zero LLM calls**:

```
@start()                        retrieve_cached   Pinecone query + Cohere rerank
@router(retrieve_cached)        check_cache       -> "cache_hit" | "cache_miss"
                                                  threshold check, no LLM
@listen("cache_miss")           scrape_web        Researcher agent, Firecrawl tools
@listen(scrape_web)             index_content     chunk / embed / upsert
                                                  (plumbing, not a tool)
@listen(or_("cache_hit", index_content))
                                write_brief       Analyst + Writer
@listen(write_brief)            persist           brief.md + Postgres row
```

Thresholds for `check_cache` are specified in `06-retrieval-layer.md` — "The
staleness gate": **≥3 reranked hits**, **top `rerank_score` ≥ 0.30**, and
**`indexed_at` ≤ 60 days**. All three must hold for `cache_hit`.

> **Naming.** The Flow's `@start` step is `retrieve_cached`; the `BaseTool` it
> calls is named `retrieve_and_rerank` (`06-retrieval-layer.md`). They are
> deliberately different identifiers — one is a Flow method, one is an agent
> tool, and `08-observability.md` string-matches `check_cache` to record
> `runs.route`.

This supersedes the hierarchical Manager: the Manager would make the same binary
decision for one LLM call per run. See `04-manager.md`.

### ⚠️ "Guardrail" means three different things in this repository

They are unrelated mechanisms and conflating them is the most common
misreading of these specs.

| Sense | What it is | Where it lives |
|---|---|---|
| **1. The deck's guardrail** (slide 28) | A *prompt-level* "what this agent must NOT do" — one of the five Agent Spec Card fields | The `Constraints:` block inside each task's `description`, and the **Guardrail** row of the spec card at the top of `01`–`05` |
| **2. CrewAI's `guardrail`** | A *post-hoc output validator* on a Task. Re-runs the task on failure. A **string** guardrail costs an LLM call every evaluation; a **callable** costs nothing | `03-writer.md` (word count) and `05-evaluator.md` (sourcing gate) — attached to `writing_task` only |
| **3. Runtime guard rails** | Execution limits: `max_iter`, `max_rpm`, `max_execution_time` | The table immediately below |
| **4. `Agent.guardrail`** | A field that exists and **does nothing inside a Crew** — it fires only on standalone `agent.kickoff()` | Nowhere, deliberately. `05-evaluator.md` says not to reach for it. |

So "every agent has a guardrail" is true in sense 1 and false in sense 2 — only
`writing_task` carries a CrewAI `guardrail:`. A student filling in slide 28's
spec card wants sense 1.

### Per-agent guard rails

This table is the single source of truth. Where an agent file deviates, the
deviation and its reason are recorded here too — if the two ever disagree, this
table is wrong and should be corrected, not worked around.

| Setting | Researcher | Analyst | Writer | Manager | Evaluator | Notes |
|---|---|---|---|---|---|---|
| `max_iter` | **15** | 10 | 10 | **20** | **5** | Default is **25**. 20 on the Manager because delegation adds round-trips; 5 on the Evaluator because a fixed checklist needs no exploration. Hitting the cap means the task is vague. |
| `max_execution_time` | 300 | 300 | 300 | **600** | 300 | 600s on the Manager: the crew-wide 300s is sized for a single worker turn, and delegation is manager → worker → manager. |
| `max_rpm` | **10** | — | — | — | — | The only agent making bursty tool calls. |
| `inject_date` | **`True`** | — | — | — | — | Time-sensitive lookups; also required for the staleness gate. |
| `respect_context_window` | `True` | `True` | `True` | `True` | `True` | The default. Stated on the Researcher only because it is the one agent whose context can actually fill. |
| `allow_delegation` | `False` | `False` | `False` | **`True`** | `False` | Exactly one agent in the crew delegates. On the Manager it is forced to `True` by `_create_manager_agent()` regardless of what you set (`04-manager.md`). |
| `reasoning_effort` | — | — | — | — | **`"minimal"`**, via `extra_body` | `glm-5.3-flash` reasons by default and bills reasoning at the completion rate. Measured 8.8× cheaper on short mechanical calls. ⚠️ The `LLM(reasoning_effort=...)` field is silently dropped for non-o1 models — it must go through `additional_params={"extra_body": {"reasoning": {...}}}`. See §3. **Not set in `src/` today, so the saving is unrealised.** |
| `guardrail_max_retries` | — | — | **2** | — | **2** | Task-level, not agent-level. Default is 3; 2 because each retry re-runs the whole task *plus* a judgement call (`03-writer.md`, `05-evaluator.md`). |
| `memory` | — | — | — | — | — | **`False`** at the **Crew** level. Keeps the OpenAI embedder unreachable. |

### Counting calls and cost

`crew.kickoff()` returns `CrewOutput` with `token_usage: UsageMetrics` —
`total_tokens`, `prompt_tokens`, `cached_prompt_tokens`, `completion_tokens`,
`reasoning_tokens`, `cache_creation_tokens`, and **`successful_requests`** (the
LLM call count). Crew-level totals only; for per-agent breakdown subscribe a
`BaseEventListener` to `LLMCallCompletedEvent`, which carries `task_id` and
`agent_id`.

There is **no cost field, and OpenRouter's does not reach you through CrewAI.**
`_extract_openai_token_usage` (`completion.py:2720`) whitelists only token counts,
and CrewAI never sets `extra_body={"usage":{"include":True}}` — so cost is
neither requested nor passed through. Verified with a real call: `event.usage`
contains no `cost` key.

**Compute cost from the token counts and the §3 price table**, keyed on
`event.model`.

**Observability — CrewAI AMP tracing plus a Postgres `run_metrics` table — is
specified in `08-observability.md`**, including why LiteLLM and LangSmith were
rejected and why authenticated tracing cannot run on Render.

### Async note

`Crew.kickoff_async()` is literally `asyncio.to_thread(self.kickoff, ...)`
(`crew.py:1182`) — not native async. Each concurrent run consumes a thread-pool
slot.

**But 1.15.18 also ships `Crew.akickoff()` (`crew.py:1210`), which is genuinely
native async**, along with `akickoff_for_each` (`crew.py:1308`). If you are inside
FastAPI, that is the method to reach for — it does not burn a thread-pool slot,
and the queue-or-worker advice below is a constraint of `kickoff_async`, not of
async execution as such.

On either path: construct a fresh `Crew` per run rather than sharing one
module-level instance. And note the thread-pool slot is not the binding limit
here anyway — the ~210 MB resident footprint (§2) caps a Render `starter`
instance at **one concurrent crew run** regardless of which method you call.

---

## 9. Documentation traps

Confirmed by running 1.15.18. Following the docs here costs you time.

| Doc says | Reality |
|---|---|
| OpenRouter "uses LiteLLM, add it as a dependency" | Native provider. Do not install the extra. |
| `LITELLM_SUCCESS_CALLBACKS` wires up Langfuse/LangSmith | Only on the **litellm fallback path** — never fires for OpenRouter. And setting it alone assigns nothing unless `LITELLM_FAILURE_CALLBACKS` is also set. |
| `extra_headers=` for ranking headers | Field does not exist; silently ignored. Use `default_headers`. |
| `from firecrawl import ScrapeOptions` | `ImportError` on firecrawl-py 4.x. Use `firecrawl.v2.types`. |
| Render Postgres plan `basic-256mb` | API wants `basic_256mb` (underscores). |
| OpenRouter has no embedding models | It has 34 — the default `/models` listing hides them. |
| `dimensions=` works on any embedder | chromadb gates it on a `"text-embedding-3"` substring. |

| Windows console encoding is a non-issue | **cp1252 silently destroys the entire verbose trace.** See below. |
| `CREWAI_DMN=true crewai create` scaffolds non-interactively | **Fails with exit 2.** `CREWAI_DMN` is enterprise *non-interactive* mode, and it makes TYPE and NAME **required** rather than optional: `Error: TYPE is required when CREWAI_DMN is set.` Use `CREWAI_DMN=true crewai create flow <name>`. Bare `crewai create` opens a TUI picker that needs a TTY, so in CI or any piped shell the DMN form with both arguments is the only one that works. |
| `crewai install` just installs dependencies | It runs `uv sync`, which makes the venv **exactly** match `pyproject.toml`. Anything not in the default dependency set is **uninstalled** — here it removed `fastapi`, `sqlalchemy`, `psycopg` and `greenlet`, correctly, because they sit in the optional `service` extra. It also writes `uv.lock`, which `07-deployment.md` needs at the repo root for Render. |

The standalone `crewAIInc/crewAI-tools` GitHub repo is **archived**; current
source is in `crewAIInc/crewAI` under `lib/crewai-tools/`.

### ⚠️ Windows: cp1252 silently destroys the verbose trace

**Measured on this machine, 2026-08-29.** Python defaults `stdout` to cp1252 on
Windows. CrewAI's event handlers print emoji — `🔧 Tool Execution Started`,
`✅ Tool Execution Completed` — and cp1252 cannot encode them, so **every handler
raises**:

```
[CrewAIEventsBus] Sync handler error in on_tool_usage_started:  'charmap' codec
[CrewAIEventsBus] Sync handler error in on_agent_logs_execution: 'charmap' codec
[CrewAIEventsBus] Sync handler error in on_task_failed:          'charmap' codec
[CrewAIEventsBus] Sync handler error in on_crew_failed:          'charmap' codec
```

**Handler exceptions never break a run** (`08-observability.md` says so, and it
is true) — which is precisely what makes this dangerous. The crew runs to
completion, costs full price, and produces *no usable trace*. On the first real
run here it swallowed the tool calls, the task failure and the crew failure
alike; the only reason the cause was visible at all was the Python traceback
underneath.

The trace is not a debugging convenience in this project — slide 50 says watch
it, slide 53 asks you to show it, and `00` §8 calls `verbose=True` "the only view
you have of who handed off to whom". Losing it silently is losing the
deliverable.

`PYTHONIOENCODING=utf-8` fixes it, but relying on an env var means the trace
breaks for whoever forgets. `src/brief_crew/__init__.py` reconfigures the streams
on import instead, so it is fixed for every entry point:

```python
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (_stream.encoding or "").lower() not in ("utf-8", "utf8"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
```

This is the same root cause as the known `crewai traces status` crash
(`UnicodeEncodeError` on U+26AA), but far broader in effect: that one crashes
loudly, this one fails silently.

---

## 10. Where things are specified

| File | Contents |
|---|---|
| `workflow.md` | **Workflow mapping** — how the six patterns land in this build, the Human Swarm role map, per-agent I/O contracts, declared deviations |
| `patterns.md` | **Agent design patterns** — the six patterns as CrewAI mechanisms: `Process`, `ConditionalTask`, Flow `@router`, `async_execution`, `manager_agent`, `guardrail`. Source-verified against 1.15.18 |
| `01-researcher.md` | Stage 1 — Firecrawl + Pinecone retrieval; judges relevance and freshness |
| `02-analyst.md` | Stage 2 — judgement, no tools |
| `03-writer.md` | Stage 3 — the brief, provenance rules |
| `04-manager.md` | Retired stretch — kept as a documented comparison |
| `05-evaluator.md` | Sourcing gate — a task guardrail first, an optional fourth agent second |
| `06-retrieval-layer.md` | The Pinecone tool, embedding conventions, chunking, rerank, **the staleness gate** |
| `07-deployment.md` | Flow, Postgres schema, `render.yaml`, provisioned resources |
| `08-observability.md` | CrewAI AMP, the LiteLLM and LangSmith decisions, what to instrument |

---

## 11. Where things are implemented

Added 2026-08-29, when the specs above became code. Every file below is the
implementation of a section of these specs; the spec remains authoritative and
the code carries a comment pointing back to it.

| Code | Implements | Notes |
|---|---|---|
| `src/brief_crew/config.py` | §3 models and prices · §4 embeddings · §5 index · §6 rerank · `06`'s staleness gate | **The single source of truth.** Model names, the two embedding prefixes and the three router thresholds each exist in exactly one place, so they cannot drift. |
| `src/brief_crew/crews/brief_crew/config/agents.yaml` | `01`/`02`/`03` identity blocks · §8 per-agent guard rails | `role`/`goal`/`backstory` pasted verbatim. Scalar guard rails (`max_iter`, `max_rpm`, `inject_date`, …) live here; `llm` and `tools` do not, because they are objects. |
| `src/brief_crew/crews/brief_crew/config/tasks.yaml` | `01`/`02`/`03` task blocks | Six keys, not three — see the track split and cache-hit notes below. |
| `src/brief_crew/crews/brief_crew/brief_crew.py` | §8 crew assembly · `02`'s no-tools rule · `03`'s A/B candidate | `@CrewBase`. Holds only what cannot be data: LLM objects, tool instances, the guardrail list, the track switch. |
| `src/brief_crew/tools/pinecone_retrieval.py` | `06` — `retrieve_and_rerank` | The one custom `BaseTool`, because §5's `SupportedProvider` excludes Pinecone. Also exports a plain `retrieve()` the Flow calls with no agent involved. |
| `src/brief_crew/embeddings.py` | §4 | Calls OpenRouter directly. The only place either prefix constant is applied. |
| `src/brief_crew/indexing.py` | `06` write-back | Plumbing, not a tool — there is no decision content in "write this to the index". |
| `src/brief_crew/guardrails.py` | `05` Option A | Callable first (free), string second (one LLM call per evaluation). |
| `src/brief_crew/main.py` | §8 Flow · `07` | `run_crew()` is Track A, `kickoff()` is Track B. |

### Three implementation decisions the specs left open

1. **The track split is two YAML keys, not a conditional.** `01` calls the tool
   list "the single easiest thing in this spec to get wrong", so `research_task`
   (Track A, with step 0) and `research_task_scrape_only` (Track B, without) are
   separate and diffable. `BriefCrew` selects the task variant and the tool list
   together from one `track` argument, so they cannot be mismatched.

2. **The cache-hit branch needed two task variants the specs did not write.**
   On `cache_hit` the Researcher never runs, so there is no upstream task output
   for the Analyst to inherit as context — §8's Flow diagram says `write_brief`
   is "Analyst + Writer" but not where their input comes from. Implemented as
   `analysis_task_from_notes` / `writing_task_from_notes`, which take the
   retrieved passages as a `{research_notes}` input and are otherwise identical,
   deliberately: a brief built from cache must be judged by the same rules as one
   built from a live scrape. `BriefCrew(from_notes=True)` is then a two-agent crew.

3. **`context` is three-valued, and the sentinel is visible.** `Task.context`
   defaults to a `_NotSpecified` sentinel rather than `None`, which is how CrewAI
   distinguishes *unset* (inherit every prior output) from *explicit empty list*
   (no context at all). `02`'s warning is therefore exactly right, and the
   consequence is load-bearing on `writing_task`: dropping `research_task` from
   its list would silently strip every source URL, because the Analyst compresses
   them away.

### Verifying without spending tokens

Both gates are pure functions and are testable offline — the deterministic half
of this system costs nothing to check:

```python
from brief_crew.guardrails import check_mechanics   # word count, sources
from brief_crew.main import BriefFlow               # check_cache: the staleness gate
```

Confirmed 2026-08-29: `check_mechanics` rejects over-length, under-length,
too-few-URLs and missing-`## Sources` briefs and passes a valid one; `check_cache`
returns `cache_hit` only for ≥3 hits with a top rerank score ≥0.30 indexed within
60 days, and `cache_miss` for every other case **including missing `indexed_at`**
— undated material is treated as stale, never as fresh.
