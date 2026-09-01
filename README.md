# Agentic Crew AI

Two CrewAI applications sharing one Python package, plus a live web console for
the second.

**Brief Crew** turns one topic into one one-page brief — a Researcher → Analyst →
Writer pipeline sitting behind a warm vector cache, so repeat runs get cheaper.

**Validator Studio** takes a startup idea and returns a scored, cited verdict.
Six agents, three of them researching in parallel against real sources, two
human approval gates that survive a process restart, and a browser UI that draws
the agent graph and animates it as the run happens.

Neither is a demo of a framework. Both are built around a specific claim: an
agent's output is only worth what its evidence is worth, so the interesting
engineering is in the parts that refuse to let a model assert something it
cannot support.

---

## Status — read this before you judge anything

The service is **deployed and serving**, and CI is **green**. It has still
**never validated an idea against paid live services in its integrated form.**
Those sentences are not in tension, and holding all three is the single most
important thing to know about this project: a deployment that answers its health
checks is not a deployment that has done the work, and a green pipeline measures
the code against doubles, not the product against reality.

There is also a live reason *not* to make that first paid run yet, and it is not
a scheduling one — see the **Rubric** row below.

| | State |
|---|---|
| Python test suite | ✅ 660 tests, 0 failures, 1 skipped |
| Frontend unit tests | ✅ 203 tests across 19 files (Vitest + jsdom) |
| Frontend end-to-end | ✅ 7 Playwright specs — real browser, real WebSocket, both durable gates, against a no-cost backend |
| Frontend type-check + build | ✅ `vue-tsc` and `vite build` clean |
| CI | ✅ green on `ubuntu-latest` — **for the first time**, at `e539811`. The three commits before it all failed. See [CI](#ci-and-the-clean-checkout). |
| Brief Crew, live | ✅ run end to end against real OpenRouter / Firecrawl / Pinecone / Cohere; numbers below are measured |
| Deployed | ✅ **live on Render** — API, static site and PostgreSQL 18. See [Live deployment](#live-deployment). |
| Validator Studio, live | ⚠️ **launched, never finished.** Two runs were started from the deployed console on 2026-08-30 (`e0b3b65e…` 04:01, `8b5a0a78…` 05:13) and **both stopped at the scope gate** — one escalation-tier call each, well under a cent. No research branch, verdict or report has ever run against live services, so nothing end to end is proven. Every test still uses a double. |
| Rubric | ⛔ an independent adversarial pass says **"do not spend money on a live acceptance run against this rubric as it stands"** — two findings rated *Critical* are still true at head. Nothing since has touched `RUBRIC_ANCHORS`. See [`docs/rubric-review.md`](docs/rubric-review.md). |
| PostgreSQL | ⚠️ the deployed API reports `"backend":"postgresql"` on `/readyz`, so the schema now exists on a real server. The automated suite still runs on SQLite only, and two-process gate contention remains untested. |
| Fan-out speedup | ❌ the benchmark harness is built and tested; **the measurement has not been taken** |

The test suite is deliberately free to run. CrewAI crews, OpenRouter, Pinecone,
Cohere, Firecrawl, Hacker News and GitHub are all mocked or replaced with
deterministic doubles, so `git clone && npm ci && python -m unittest` costs
nothing and touches no network. The flip side is the row above: coverage is not
evidence that the live integration works.

Full, current, unflattering detail lives in [`CLAUDE.md`](CLAUDE.md) under
*Remaining Work and Unverified Risks*. It is maintained as a working handoff, not
as marketing, and it is the file to trust when this one and it disagree.

---

## Live deployment

| | |
|---|---|
| Web console | **https://agentic-crew-ai-web.onrender.com** — Render static site, free plan |
| API | **https://agentic-crew-ai-api.onrender.com** — Render web service, `python` runtime, `starter`, `singapore` |
| Database | `agentic-crew-ai-db` — Render PostgreSQL **18**, `basic_256mb`, `singapore`. Pre-existing; **reused, not recreated.** |
| Source | https://github.com/simonraj79/multi_agent_crewai_startup_advisor — public, `main`, auto-deploy on |

Both services are running **`e539811`**, redeployed after the admission-control
and CI work below.

What was verified against the deployed origin:

- `GET /healthz` returns `200`.
- `GET /readyz` returns `200` with `"storage": {"backend": "postgresql"}` — the
  service is talking to a real PostgreSQL 18 instance, not the SQLite fallback.
- `GET /api/workflows/idea-validator/graph` serves the full descriptor: **14
  nodes, 16 edges**, matching the graph the tests assert against.
- CORS behaves as configured — the API echoes
  `Access-Control-Allow-Origin` for the static site's origin and refuses a
  preflight from an unlisted one with `400`.
- `wss://agentic-crew-ai-api.onrender.com/ws` completes a `101` upgrade.
- The admission bounds are live, not just unit-tested: an oversized body is
  refused with `413` and a 2001-character idea with `422`.
- `GET /docs` returns `404` — `EXPOSE_API_DOCS` is unset on the paid instance.
- A **2-of-2 read-only Playwright smoke test** passes against the deployed web
  console (`--grep-invert @launch`, so nothing spent money).

**What was not verified: anything that costs money.** No validator run has been
launched against the deployed service. Pressing *Launch* there spends real
OpenRouter, Firecrawl and Cohere credit, so the end-to-end claim in the status
table above is still open. The deployment is live; the product is unproven.

> ⚠️ The API runs on Render's free-adjacent `starter` plan behind a proxy that
> idles instances. A first request after a quiet period can take tens of seconds
> to answer while the service wakes.

---

## What is actually interesting here

Four things in this repository are unusual enough to be worth your time even if
you never run it.

### A rubric bound to counted evidence

The validator scores an idea on five dimensions and computes a verdict
arithmetically:

```
score = 2 × (0.30·Demand + 0.20·Moat + 0.20·Competition + 0.15·Feasibility + 0.15·Headroom)
```

Any arithmetic the model supplies is **overwritten**, not trusted. But the real
work is a layer up. Each dimension has a written ladder of anchors, and two
independent guardrails police it:

- `anchor_problems` checks the *wording* — the text the model quotes must be the
  anchor for that dimension at that score, matched at 0.85 token overlap.
- `score_support_problems` checks the *findings* — the evidence actually counted
  from tool output must be able to carry the score claimed.

The second exists because the first is not enough. A model that has read the
rubric can quote the "strong demand" anchor verbatim over two stale forum
threads. Wording matching catches plagiarism of the rubric; evidence support
catches the claim. Scores are bounded from above everywhere, and from below only
at levels 0 and 1 — the two levels where a *low* score is itself a strong claim
that ought to need support. Judgement clauses are never mechanically enforced,
because pretending a judgement is a count is how you get confident nonsense.

### A router that makes the one real decision without a model

Brief Crew's cache hit-or-miss decision is the only genuinely dynamic branch in
the pipeline. It is a CrewAI `@router` returning a `Literal["cache_hit",
"cache_miss"]`, resolved from three thresholds — at least 3 reranked hits, top
rerank score at least 0.30, indexed within 60 days — for **zero LLM calls**. A
manager agent would make the identical binary decision and bill a model call per
run to do it.

Missing `indexed_at` is treated as stale, never as fresh. The validator's two
approval gates route the same way: deterministic approve/revise, no model asked.

### Human gates that survive the process dying

Both validator gates use CrewAI's native `@human_feedback`. When a run reaches
one it raises `HumanFeedbackPending`, the flow state is written to SQL, and the
process is free to exit. A reply arriving minutes or hours later — over HTTP or
over the WebSocket, through one shared compare-and-set path — rehydrates the flow
and resumes it. A duplicate reply gets HTTP 409 rather than a second run.

The gate payload is split into editable `fields` and read-only `derived` values,
and at the verdict gate *every* key is derived. Seven of them are arithmetic the
schema recomputes and discards; the rest are inputs the guardrails bind to the
rubric and to real tool URLs. Neither survives a text box. So `fields` is
**pruned** rather than annotated — a stale client cannot go on offering an edit
the server would silently throw away. The operator's lever is `decision=revise`
plus written feedback, which is the honest one.

### An event spine with a visible quarantine node

The UI is driven by an immutable, versioned frame stream with gapless per-run
sequence numbers, a bounded 2,000-frame run ring and 512-frame subscriber queues.
Serialization is field-bounded: it never walks a whole live CrewAI object.
Capture callbacks do no socket and no database I/O — frames enter a bounded queue
and a separate batching thread persists them, so database latency never reaches a
CrewAI event handler.

The part worth stealing: events that cannot be attributed to a known node are not
dropped and not silently folded into their neighbours. They are routed to a node
called `unattributed`, which is **rendered in the UI** — quiet when empty, loud
when it holds frames. An observability layer that hides its own blind spot is
worse than one that admits it, because you will believe it.

---

## What you need

| | |
|---|---|
| Python | 3.10–3.13 (**not 3.14** — CrewAI excludes it). `.python-version` pins 3.13. |
| Node | 20+ for the frontend (CI uses 24) |
| [uv](https://docs.astral.sh/uv/) | for the Python environment and the lockfile |

### API keys

Copy [`.env.example`](.env.example) to `.env` and fill it in. That file documents
the variables and names the source file that reads each one. (`SYNTHETIC` is not
in it — it is a per-invocation switch, not configuration; see
[Service configuration](#service-configuration) below.) The short version:

| Key | Needed for | Get one |
|---|---|---|
| `OPENROUTER_API_KEY` | **everything.** Every agent LLM call and every embedding. | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `FIRECRAWL_API_KEY` | web search + scrape: Brief Crew's Researcher, the validator's Market Analyst | [firecrawl.dev](https://www.firecrawl.dev/app/api-keys) |
| `PINECONE_API_KEY` + `PINECONE_INDEX_NAME` | the warm cache (Brief Crew Track B, validator market cache) | [app.pinecone.io](https://app.pinecone.io) |
| `COHERE_API_KEY` | stage-2 rerank on every retrieval | [dashboard.cohere.com](https://dashboard.cohere.com/api-keys) |
| `GITHUB_TOKEN` | **optional.** Raises the validator's GitHub search limit from 8 to 24 req/min. No scopes needed. | any GitHub PAT |

You create the Pinecone index yourself: **768 dimensions, cosine, serverless.**
The dimension is not negotiable — embeddings are truncated to 768 via the
`dimensions` parameter, and a mismatch fails upserts silently rather than
raising.

**OpenRouter is the only model provider.** There is no OpenAI fallback and
`OPENAI_API_KEY` is not used. Every model constant carries an `openrouter/`
prefix and the service refuses to start if one does not.

You can run the whole test suite with none of these set — and, with
`SYNTHETIC=1`, the whole application too. See
[Running Validator Studio](#as-a-service-with-the-web-console). As of `e539811`
that is checked by a machine that has no keys rather than asserted: CI runs from
a clean checkout with no `.env`. See [CI](#ci-and-the-clean-checkout).

### Service configuration

Not secrets. These only matter when you run the hosted service.

| Variable | Default | What it does |
|---|---|---|
| `SYNTHETIC` | unset | `1` starts `serve` with **no-cost doubles** instead of the paid runners. `src/brief_crew/service/app.py::app_from_env`. |
| `CORS_ALLOW_ORIGINS` | *empty* | Comma-separated **origins** — scheme, host, optional port, no trailing slash — allowed to call `/api`. Empty means no cross-origin caller at all. |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address. A container or PaaS needs `HOST=0.0.0.0`. |
| `DATABASE_URL` | *unset* | PostgreSQL when set; SQLite at `output/validator-studio.db` when not. |
| `RUN_CONCURRENCY` | `1` | Concurrent runs; the rest queue. One run is the memory ceiling on a 512 MB instance. |
| `RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS` | `5.0` | How long a resubmission waits for a still-settling run future before refusing the caller. |
| `MAX_QUEUED_RUNS` | `8` | Runs queued or executing, across every caller, above which a **new** run gets `429`. The keyless cost bound. |
| `RUN_RATE_LIMIT_MAX_RUNS` | `10` | Per-client run-creation burst. **`0` disables the limiter** — the intended escape hatch for load testing. |
| `RUN_RATE_LIMIT_WINDOW_SECONDS` | `60.0` | The window that burst refills over. |
| `RUN_RATE_LIMIT_TRUST_FORWARDED_FOR` | `true` | Key the limiter on the leftmost `X-Forwarded-For` entry. **Turn it off** where the service is reachable directly and the socket peer is the real client. |
| `EXPOSE_API_DOCS` | `false` | Serve `/docs`, `/redoc` and `/openapi.json`. Off by default on a paid app; **forced on** for a synthetic one. |
| `PINECONE_INDEX_NAME` | *unset* | Named above under [API keys](#api-keys); it is read in `config.py` like the rest of this table. |
| `VALIDATOR_FEASIBILITY_CACHE_ENABLED` | `false` | Opt the feasibility branch into the warm cache as a GitHub rate-limit shock absorber. |
| `VALIDATOR_SEQUENTIAL_BRANCHES` | `false` | Withdraw the three-way fan-out to one-at-a-time without a code edit. Parallel stays the shipped default. |

Everything above is read at **import time** in
[`src/brief_crew/config.py`](src/brief_crew/config.py) — except `SYNTHETIC`,
`HOST`, `PORT` and `DATABASE_URL`, which
`src/brief_crew/service/app.py` reads. A malformed value for any of the numeric
ones **stops startup** rather than being silently coerced.

**The rest of the admission-control settings are constants, not knobs.** They
are deliberately not environment-tunable, so changing one is a code edit and a
commit rather than a dashboard field nobody remembers setting:

| Constant | Value | What it bounds |
|---|---|---|
| `MAX_REQUEST_BODY_BYTES` | 64 KiB | The declared `Content-Length` of any HTTP request. Matches `WS_MAX_MESSAGE_BYTES`, so both transports agree on "too big". |
| `MAX_RUN_INPUT_CHARS` | 2000 | One run input — `inputs.idea` or `inputs.topic`. This is the token-amplification bound. |
| `MAX_RUN_INPUT_KEYS` / `MAX_RUN_INPUT_BYTES` | 16 / 8 KiB | The shape of the whole `inputs` mapping, which is typed `dict[str, Any]`. |
| `RUN_ADMISSION_RETRY_AFTER_SECONDS` | 30 | The `Retry-After` on a capacity refusal — a fixed hint, deliberately not a live queue-depth estimate. |
| `RUN_RATE_LIMIT_MAX_CLIENTS` / `RUN_RATE_LIMIT_KEY_MAX_CHARS` | 4096 / 64 | The limiter's own memory, since its map is keyed by attacker-supplied text. |

`CORS_ALLOW_ORIGINS` is invisible locally — Vite proxies `/api` and `/ws` to the
API, so every request is same-origin and no CORS header is ever involved. It is
load-bearing in production, where the Vue app is a **separate** static site and
the browser discards every response the API does not opt into by name. The empty
default is deliberate: a new deployment fails closed and the operator names the
frontend origin on purpose, rather than the service shipping `*` and nobody ever
revisiting it. A malformed value **stops startup** and the error names the
corrected string — a trailing slash is the common way to get this wrong, because
a browser never sends one in an `Origin` header, so it would match nothing and
fail as though the middleware were missing.

It does **not** govern `/ws`. Browsers do not apply CORS to a WebSocket
handshake, and Starlette's middleware passes non-HTTP scopes straight through, so
any page can open the socket. What it cannot do is guess the uuid4 `run_id` and
the `session_id` the socket demands before it sends a frame.

---

## Install

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv -e .

# The hosted service (FastAPI, SQLAlchemy, psycopg) is an optional extra:
uv pip install --python .venv -e '.[service]'
```

> ⚠️ `crewai install` runs `uv sync`, which **uninstalls** anything absent from
> `pyproject.toml`'s default dependencies — including the whole `service` extra.
> If the API stops importing after you run it, that is why. Reinstall the extra.

> ⚠️ **`.venv` has no `pip` and no `pytest`.** `uv venv` does not seed pip, so
> `python -m pip ...` fails with `No module named pip` — read versions from
> `importlib.metadata` instead. `[tool.pytest.ini_options]` in `pyproject.toml`
> is inert; the suite is `unittest`, and so is CI.

Exact versions of everything installed, and the commands that regenerate them,
are in [`docs/tech-stack.md`](docs/tech-stack.md).

---

## Running Brief Crew

Two tracks over the same three agents.

|  | **Track A** — `run_crew()` | **Track B** — `kickoff()` |
|---|---|---|
| Orchestration | `Process.sequential` | `Flow` with a deterministic `@router` |
| Who checks the cache | the Researcher, as a tool | the Flow, *before* any agent runs |
| Researcher tools | 3 | 2 |
| Needs | API keys only | + Pinecone, Cohere |

**Start with Track A.** Everything else presupposes a working sequential crew.

```bash
.venv/Scripts/python -c "from brief_crew.main import run_crew; run_crew('your topic')"   # Track A
.venv/Scripts/python -c "from brief_crew.main import kickoff;  kickoff('your topic')"    # Track B
```

The brief lands in `output/brief.md`; Track B also writes `output/last_run.json`.

```
                      ┌──────────────────────┐
   topic ────────────▶│   retrieve_cached    │  Pinecone + Cohere
                      └──────────┬───────────┘
                        ┌────────▼────────┐
                        │  check_cache    │   relevance + freshness
                        └───┬─────────┬───┘   0 LLM calls
                     miss   │         │  hit
                    ┌───────▼──────┐  │
                    │  Researcher  │  │       Firecrawl search + scrape
                    └───────┬──────┘  │
                    ┌───────▼──────┐  │
                    │ index_content│  │       chunk / embed / upsert
                    └───────┬──────┘  │
                            └────┬────┘
                        ┌────────▼────────┐
                        │     Analyst     │   no tools — judgement only
                        └────────┬────────┘
                        ┌────────▼────────┐
                        │     Writer      │   no tools — prose only
                        └────────┬────────┘
                                 ▼
                          output/brief.md
```

> ⚠️ **Known gap.** Cache write-back carries no structured provenance. The cache
> genuinely warms — one miss writes chunks, the next run hits — but every chunk
> is stored with `url=""` and `publisher=""`, because the Flow indexes the
> Researcher's *notes* rather than the scraped *pages*. Briefs are unaffected
> (the URLs survive inside the chunk text) but per-source provenance cannot be
> reconstructed. Detail in [`agents/06-retrieval-layer.md`](agents/06-retrieval-layer.md).

---

## Running Validator Studio

Six agents. Two of them — Scoper and Synthesist — and the Reporter have **no
tools at all**; that boundary is deliberate, and it is what keeps judgement
separate from retrieval.

| Agent | Model tier | Tools |
|---|---|---|
| Scoper | escalation | none |
| Market Analyst | cheap | Firecrawl search + scrape |
| Sentiment Analyst | cheap | Hacker News (Algolia) |
| Feasibility Analyst | cheap | GitHub repository search |
| Synthesist | escalation | none |
| Reporter | escalation | none |

```
scope ─▶ scope gate ─┬─▶ market      ─┐
                     ├─▶ sentiment   ─┼─▶ synthesis ─▶ verdict gate ─▶ report
                     └─▶ feasibility ─┘                                  │
                                                                         ▼
                                                            output/validation.md
```

The three research branches are sibling `@listen` methods on one event, so CrewAI
runs them concurrently in worker threads, with an `and_()` fan-in before
synthesis.

### From the command line

```bash
.venv/Scripts/validate --idea "A scheduling assistant for clinics"
```

This stops at both human gates and waits for you. To skip them:

```bash
.venv/Scripts/validate --idea "A scheduling assistant for clinics" --no-gates
```

> ⚠️ `--no-gates` skips the *approvals*, not the *spending*. A real `--no-gates`
> run still calls paid models and external tools.

### As a service, with the web console

Two processes. **Start the API in synthetic mode** — this is the way to try the
app:

```bash
SYNTHETIC=1 .venv/Scripts/serve     # http://127.0.0.1:8000, spends nothing
```

Then the frontend:

```bash
cd frontend
npm install
npm run dev                         # http://localhost:5173
```

The dev server proxies `/api` and `/ws` to `127.0.0.1:8000`, so no configuration
is needed locally. Open `http://localhost:5173/`.

> ⚠️ **`serve` without `SYNTHETIC=1` is the paid service.** It builds the real
> crew runners, so the first time anyone presses *Launch* — to look at the graph,
> to check the UI renders, to see what the thing does — it calls OpenRouter,
> Firecrawl, Hacker News and GitHub for real and bills you. Nothing in the UI
> distinguishes the two modes. `SYNTHETIC=1` selects the same no-cost doubles the
> integration tests use: real frames, real WebSocket, both durable gates, no
> spend and no API keys required.
>
> Use the paid mode when you actually mean to validate an idea.

**If no backend answers, the UI falls back to a scripted mock and shows a
complete, entirely fabricated run.** This is deliberate — it makes the UI
developable and testable without a backend — but it means a misconfigured
deployment fails by showing you plausible fiction rather than an error. The
single most common cause is `VITE_API_URL` set to a bare hostname instead of a
full origin; see [`docs/deploying.md`](docs/deploying.md).

### The API

```
GET  /healthz
GET  /readyz
GET  /api/workflows
GET  /api/workflows/{workflow_id}/graph
POST /api/sessions/{session_id}/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/frames
POST /api/runs/{run_id}/gates/{gate_id}
POST /api/runs/{run_id}/cancel
GET  /api/runs/{run_id}/logs?format=ndjson|zip
WS   /ws?session_id=&run_id=&after=
```

Run state, frames and gates persist to SQL — SQLite at
`output/validator-studio.db` by default, PostgreSQL when `DATABASE_URL` is set.
Cancellation is cooperative and lands at the next CrewAI step boundary.

`/docs`, `/redoc` and `/openapi.json` return **404 unless `EXPOSE_API_DOCS=1`**
(or the app is synthetic). That is obscurity, not a control — the endpoints are
unchanged and a reader can still find them.

### What the run endpoint refuses

`POST /api/sessions/{session_id}/runs` is the only endpoint that spends money and
it is **unauthenticated** — the deployed API serves an open demo, so anyone may
call it and the owner pays for the run. These bounds are the defence in depth
that replaces a login, chosen to be invisible to one honest visitor pressing
*Launch* and expensive for a script:

| Condition | Status | Response |
|---|---|---|
| Body larger than 64 KiB | **413** | `the request body is limited to 65536 bytes` — refused by ASGI middleware on the declared `Content-Length`, before FastAPI or pydantic parses anything |
| Over the per-client rate limit | **429** | `too many runs from this client; wait and try again`, plus a computed `Retry-After` |
| Server at the admission cap | **429** | `the service is at capacity; try again shortly`, plus `Retry-After: 30` |
| `inputs.idea` / `inputs.topic` over 2000 chars | **422** | `inputs.idea is limited to 2000 characters; this one is N` |
| `inputs` over 8 KiB of JSON, or over 16 keys | **422** | a pydantic value error naming the bound |
| Unknown `workflow_id` | **404** | `workflow not found` |

Two carve-outs are deliberate and tested:

- **A run waiting at a gate holds no admission slot.** It has already returned
  its worker thread, so a human thinking about a scope does not consume capacity
  from anyone else.
- **A gate reply is never refused for capacity.** It belongs to a run the caller
  already holds, and refusing one would strand a human mid-run. A flood must not
  be able to do that.

The rate limit runs *first*, ahead of the workflow and input checks, so a flood
of deliberately malformed bodies is throttled too. It is the only endpoint
limited at all — `/healthz`, `/readyz` and every read-only `GET` are left alone,
so monitoring and a reconnecting UI are never affected.

> ⚠️ **The rate limit is a courtesy limiter, not a security control**, and
> `config.py` says so at length. It is an in-process token bucket in one
> instance: it resets on every deploy, it multiplies by the instance count if the
> service is ever scaled out, and its key is an IP that the client writes via
> `X-Forwarded-For`. Anyone willing to rotate a header walks past it. The layer
> that holds against someone actually trying is `MAX_QUEUED_RUNS`, because that
> one is keyless and cannot be rotated around.

Covered by `tests/service/test_run_admission.py` — 37 tests, including the two
carve-outs, thread-safety of the bucket, and that hiding the docs does not hide
the API.

---

## Tests

```bash
.venv/Scripts/python -m unittest discover -s tests -t .    # 660 tests

cd frontend
npm run build                                              # vue-tsc -b && vite build
npm test                                                   # 203 tests, vitest run
```

All three are free to run and touch no network.

### End to end, in a real browser

Seven Playwright specs drive the operator's journey — launch, both durable gate
round trips over a real WebSocket, the verdict gate's read-only fields, reload
recovery — against a real FastAPI service. Start the **free** backend first:

```bash
SYNTHETIC=1 PORT=8099 .venv/Scripts/serve

cd frontend
npx playwright install chromium     # once
npm run test:e2e                    # 7 tests
```

The suite starts its own Vite server (`frontend/e2e/vite.e2e.config.ts`) pointed
at port 8099, so `vite.config.ts` — which proxies to the *paid* service on 8000 —
is never used and the suite cannot launch a paid run.

The same specs run against a deployed origin:

```bash
E2E_BASE_URL=https://agentic-crew-ai-web.onrender.com \
  npx playwright test --grep-invert @launch
```

> ⚠️ **`--grep-invert @launch` is not optional against production.** The five
> tests that press Launch are tagged `@launch`; a deployed API is backed by paid
> runners, so without that flag every smoke test spends real money on a full
> six-agent run. What is left is the read-only half — topology, and that the page
> reached the live backend rather than falling through to its mock.

### CI and the clean checkout

GitHub Actions runs the Python suite and the frontend build/unit tests on
`ubuntu-latest`. As of `e539811` both jobs pass — **the first green run in this
repository's history.** The three commits before it failed, and it is worth being
precise about why, because the cause was not a broken test.

No `.env` is ever committed, so CI starts from a genuinely clean checkout. But
`brief_crew/__init__.py` calls `load_dotenv(..., override=True)` at import time,
and around 40 tests *construct* real `LLM` and Firecrawl objects in order to
assert their wiring — which model a crew was given, which tools an agent carries,
that the Reporter has none. Nothing ever *calls* those objects, but both
constructors demand a key and refuse to build without one. On a machine with a
real `.env` the suite passed; on CI it collapsed at object construction in ~5s
with 4 failures and 36 errors.

The fix is `tests/__init__.py`, which runs before anything imports `brief_crew`
and `setdefault`s two obviously-fake placeholders. Three rules govern it, and
they are written out in the module docstring: `setdefault` and never assignment,
so a developer's real keys still win; a value that could not be mistaken for a
credential in a traceback or a screenshot; and only the variables an actual
failure demands, so it does not become a mirror of `.env.example` masking real
assertions.

The practical consequence is worth stating on its own: **`git clone && uv pip
install -e . && python -m unittest` now passes with no keys and no `.env` at
all.**

The Playwright suite is **not** in CI — that job would need the `SYNTHETIC=1`
backend started alongside it plus a browser download.

> ⚠️ **If you add a test directory, add its `__init__.py` in the same commit.**
> This suite reported 65 passing tests for a long time and that number was a lie:
> `tests/events/` and `tests/service/` had no `__init__.py`, so `unittest
> discover` walked straight past the entire event spine and service layer and
> printed a green `OK`. Discovery does not warn you. (`pyproject.toml` configures
> pytest, which collects by rootdir and would have caught it — but pytest is not
> in the default dependency set.)

Test counts move. The command is the contract, not the figure.

---

## What it costs

### Brief Crew — measured, one run each, cold cache

| | Track A | Track B (`cache_miss`) |
|---|---|---|
| LLM calls | 9 | 13 |
| Prompt tokens | 178,711 | 109,104 |
| Completion tokens | 13,614 | 30,085 |
| Wall time | ~7 min | ~7 min |
| Cost | $0.017 – $0.185 | ≤ $0.1946 (upper bound) |

The ranges are wide for an honest reason: crew-level token usage is not split by
model, so the upper bound prices every call at the escalation tier. Track B's
four extra calls are the cache round-trip — overhead paid on every miss and
repaid only by a later hit.

**72% of Track A's completion tokens were reasoning tokens** (9,757 of 13,614),
billed at the completion rate. That is the largest untaken cost lever in the
project.

### The architecture only pays for itself if runs repeat

A cache **miss** costs *more* than the plain crew, not less — it does everything
the crew does plus retrieve, rerank, embed and upsert. A cache **hit** skips
search and scrape entirely and is markedly cheaper. The first run on any topic is
always the expensive one. That is the design working, not failing.

### Validator Studio

**Unmeasured.** It has never been run end to end against live services, so any
figure here would be invented. Structurally it is one escalation-tier scope, three
cheap-tier research branches with real tool calls, then two escalation-tier
passes — expect it to cost more than a Brief Crew run, and do not quote a number
until someone has taken one.

### Hosting

About **$13.30/month** fixed on Render — `$6.30` Postgres `basic_256mb` with 1 GB,
`$7.00` for the API on `starter`, `$0` for the static frontend. Model tokens,
Firecrawl calls and Cohere rerank units are on top.

---

## Deploying

It is deployed. See [Live deployment](#live-deployment) for the URLs and for
exactly what was and was not verified there.

`render.yaml` is a complete Render Blueprint for the API, the static frontend and
a PostgreSQL 18 database, and it remains the readable description of the target
shape. **The live services were not created from it** — they were created
directly against the Render API, against the same GitHub repository, and the
pre-existing `agentic-crew-ai-db` was reused rather than redefined.
[`agents/07-deployment.md`](agents/07-deployment.md) records what is actually
running and where the manifest and the reality differ.

There are two ways to get this wrong that fail *silently* rather than loudly, and
both are covered step by step in **[`docs/deploying.md`](docs/deploying.md)**.
Read it before you touch the deployment.

---

## Layout

```
src/brief_crew/
├── config.py                  models · prices · thresholds · rubric anchors
├── embeddings.py              OpenRouter embeddings, called directly
├── indexing.py                chunk / embed / upsert
├── guardrails.py              Brief Crew's evaluator gate
├── main.py                    run_crew() = Track A · kickoff() = Track B
├── validator_flow.py          the six-agent flow, gates, routers, fan-out
├── validator_guardrails.py    scope, URL closure, evidence counts, rubric binding
├── validator_cache.py         validator cache policy and namespacing
├── schemas/validator.py       Evidence · Verdict · ValidationReport · …
├── crews/                     @CrewBase wiring + agents.yaml / tasks.yaml
├── tools/                     Firecrawl · Hacker News · GitHub · Pinecone
├── events/                    the frame spine, registry and serializer
└── service/                   FastAPI, WebSocket, SQL persistence, run registry

frontend/                      Vue 3 + TypeScript + Vite + Vue Flow console
├── tests/                     203 Vitest specs over 19 files
└── e2e/                       7 Playwright specs
agents/                        the authoritative specifications
tests/                         660 tests, all free to run
docs/                          deployment and licensing notes
```

**Prompts are data, wiring is code, and constants are neither duplicated nor
inlined.** `agents.yaml` and `tasks.yaml` hold every word an agent reads;
`config.py` holds every model name, price, embedding prefix and threshold, exactly
once. If you find a model name or a threshold inlined in Python, that is a bug.

---

## Three things to know before changing anything

**1. `Task.context` is three-valued.** Unset means *inherit every prior output*;
an explicit list means *exactly these*; an empty list means *nothing at all*.
CrewAI models this with a `_NotSpecified` sentinel rather than `None`. Trimming
`writing_task`'s context to `[analysis_task]` looks like tidying and silently
strips every source URL, because the Analyst compresses them away.

**2. An agent's tool list and its task description must change together.** Track
A's task tells the Researcher to call the retrieval tool first; Track B's does
not, because the Flow already retrieved and already failed the staleness gate. An
agent told to call a tool it does not have **will invent the result** — that is
the direct cause of fabricated citations. Both are selected from one `track`
argument so they cannot be mismatched.

**3. Do not route embeddings through CrewAI.** ChromaDB forwards the `dimensions`
parameter only when the model name contains `"text-embedding-3"`. The model used
here fails that test, so `dimensions=768` is dropped silently and 3072-dim vectors
are sent to a 768-dim index — no error, just failed upserts a long way from the
cause. Call `brief_crew.embeddings` directly, and keep `DOC_PREFIX` and
`QUERY_PREFIX` paired.

---

## Documentation

| File | What it is |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **The honest handoff.** What is implemented, what is not, and what is unverified. Read it before believing anything else. |
| [`agents/`](agents/) | The authoritative specifications. Where code and spec disagree, the spec is right and the code is a bug. |
| [`AGENTS.md`](AGENTS.md) | CrewAI reference for anyone — human or coding agent — changing crew code. |
| [`PRD.md`](PRD.md) | The requirements document that extends `agents/` into Validator Studio. |
| [`new features/feature-list.md`](new%20features/feature-list.md) | Feature ledger. Every row names the test or source path it rests on. |
| [`docs/tech-stack.md`](docs/tech-stack.md) | **Every version, pin and toolchain quirk**, with the command that regenerates each figure. Interpreter, packages, models, external API versions, the twenty environment knobs, and the open stack-hygiene defects. Check a version here, not in prose. |
| [`docs/deploying.md`](docs/deploying.md) | Post-push Render checklist. |
| [`docs/preflight.md`](docs/preflight.md) | What to check before the first **paid** validator run — credentials, the live path, cost estimate, failure modes. |
| [`docs/rubric-review.md`](docs/rubric-review.md) | An independent adversarial pass over the five rubric ladders, `rubric_support` and the verdict arithmetic. Written by an agent that had no part in the derivation — which is not the same as a human having read them. |
| [`docs/licensing.md`](docs/licensing.md) | Licence options and the decision still to be made. |

The four official CrewAI agent skills are vendored into `.agents/skills/` and
`.claude/skills/` (installed with `npx skills add crewaiinc/skills`, MIT). They
are committed on purpose, so any coding agent that opens this repository gets the
same CrewAI guidance without a separate install step.

---

## Author and licence

**Author: Simon Raj.** Every word of prose and every line of code in this
repository is his own work — the CrewAI implementation, the six-agent validator,
the event spine, the FastAPI / WebSocket service, the Vue 3 console, the
specifications in [`agents/`](agents/), the scoring rubric and every test.
Copyright © 2026 Simon Raj.

Where it builds on published thinking it cites a public source. Five of the six
orchestration *pattern names* used in
[`agents/workflow.md`](agents/workflow.md) §3 — prompt chaining, routing,
parallelisation, orchestrator-workers, evaluator-optimizer — are Anthropic's,
from [*Building Effective Agents*](https://www.anthropic.com/engineering/building-effective-agents),
and are cited there directly; the sixth is this repository's own. The analysis of
how each pattern maps onto CrewAI 1.15.18 is original throughout. The only
third-party *files* in the repository are the four vendored MIT CrewAI skills
noted above.

**No `LICENSE` file exists**, which means default copyright applies: you may read
this code but not legally reuse it. [`docs/licensing.md`](docs/licensing.md) sets
out the options — or open an issue and ask.

---

## A note on traces

`crewai traces enable` before a run gives you a shareable trace URL. Traces can
include prompts, task inputs and outputs, tool arguments and results, and model
responses. Check what a trace actually contains before you share the link.
