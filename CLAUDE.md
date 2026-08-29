# CLAUDE.md

## Read This First

This repository now contains two applications that share one Python package:

1. **Brief Crew** - the original Researcher -> Analyst -> Writer pipeline with a warm Pinecone cache.
2. **Validator Studio** - an additive six-agent startup validator with a FastAPI/WebSocket service and Vue 3 + Vue Flow UI.

Read [`AGENTS.md`](AGENTS.md) before changing CrewAI code. The specifications in [`agents/`](agents/) remain authoritative for behavior they already cover. [`PRD.md`](PRD.md) extends those specifications for Validator Studio.

The top status table in [`new features/feature-list.md`](new%20features/feature-list.md) predates much of the implementation and is not a reliable completion ledger yet. Use this file plus executable tests until that ledger is reconciled.

## Verified Baseline

Verified on 2026-08-29:

```text
CrewAI: 1.15.18
Python tests:   254 run, 0 failures, 0 errors, 1 skipped
Frontend tests:  64 run, 0 failures (Vitest + jsdom)
Frontend build: vue-tsc and Vite production build passed
```

Commands used:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .

Push-Location frontend
npm run build
npm test
Pop-Location
```

> The Python count was **65 for a long time, and that number was wrong.**
> `tests/events/` and `tests/service/` had no `__init__.py`, so
> `unittest discover` walked past them in silence - a green `OK` that never ran
> the event spine or any of the service layer. Both are packages now. If you
> ever add a test directory, add its `__init__.py` in the same commit, or
> discovery will hide it and tell you everything passed.
>
> `pyproject.toml` configures pytest, which collects by rootdir and would have
> caught this - but pytest is not installed in `.venv`.

The test suite is deliberately no-cost: CrewAI crews, external APIs, OpenRouter, Pinecone, Cohere, and Firecrawl are mocked or replaced with deterministic runners where needed.

## Non-Negotiable Platform Rules

- **OpenRouter only.** All agent LLMs use `CHEAP_MODEL` or `ESCALATION_MODEL` from [`src/brief_crew/config.py`](src/brief_crew/config.py).
- **No direct OpenAI fallback.** Validator Studio does not require `OPENAI_API_KEY`. Service startup rejects model constants or YAML-level model overrides that do not use the `openrouter/` prefix.
- **Do not install `crewai[litellm]`.** OpenRouter is a native provider in CrewAI 1.15.18.
- **Call embeddings directly through `brief_crew.embeddings`.** Do not use CrewAI's embedder. Keep `DOC_PREFIX` and `QUERY_PREFIX` paired.
- **Prompts stay in YAML.** Agent and task instructions belong in `config/agents.yaml` and `config/tasks.yaml`, never Python.
- **Constants stay in `config.py`.** Do not inline model names, prices, embedding prefixes, routing thresholds, cache policies, or runtime limits.
- **No tools on Scoper, Synthesist, or Reporter.** Their `tools=[]` boundary is deliberate.
- **Do not regress Brief Crew.** Preserve `run_crew()`, `kickoff()`, `output/brief.md`, and `output/last_run.json` behavior.

## What Has Been Implemented

### 1. Brief Flow Graph Repair

[`src/brief_crew/main.py`](src/brief_crew/main.py) now annotates `check_cache()` as:

```python
Literal["cache_hit", "cache_miss"]
```

CrewAI static graph introspection now sees all six Brief Flow edges, including both cache routes. This fixes the disconnected graph described in PRD section 9.0 without changing runtime routing.

### 2. Six-Agent Validator

Implemented under [`src/brief_crew/crews/validator_crew/`](src/brief_crew/crews/validator_crew/):

| Agent | OpenRouter tier | Tools |
| --- | --- | --- |
| Scoper | Escalation | none |
| Market Analyst | Cheap | Firecrawl market research |
| Sentiment Analyst | Cheap | Hacker News Algolia |
| Feasibility Analyst | Cheap | GitHub repository search |
| Synthesist | Escalation | none |
| Reporter | Escalation | none |

The implementation uses five single-agent Crew wrappers around six agents. All prompts and output contracts are YAML-first.

### 3. Validator Flow

[`src/brief_crew/validator_flow.py`](src/brief_crew/validator_flow.py) implements:

```text
scope -> scope gate -> three parallel research branches
      -> synthesis -> verdict gate -> report -> output/validation.md
```

Key behavior:

- Structured `ValidatorState`.
- Native CrewAI `@human_feedback` at both gates.
- Deterministic routers for approve/revise decisions with no LLM routing call.
- Three sibling synchronous `@listen("scope_approved")` methods, so CrewAI runs branch crews concurrently in worker threads.
- `and_()` fan-in before synthesis.
- Dependency-injected crew factories for no-cost tests.
- `no_gates=True` mode for CI and headless deterministic execution.
- Native `HumanFeedbackPending` pause, persistence, `from_pending()`, and `resume()` lifecycle.
- Final Markdown is written by the Flow persistence step, not by `Task.output_file`.

CLI entry point:

```powershell
.\.venv\Scripts\validate.exe --idea "A scheduling assistant for clinics"
```

For tests or explicitly auto-approved execution:

```powershell
.\.venv\Scripts\validate.exe --idea "A scheduling assistant for clinics" --no-gates
```

A real no-gates run still calls paid models and external tools unless crew factories are replaced with test doubles.

### 4. Structured Schemas and Deterministic Verdict

[`src/brief_crew/schemas/validator.py`](src/brief_crew/schemas/validator.py) contains the validator contracts:

- `Evidence`
- `Competitor`
- `Thread`
- `Repo`
- `DimensionScore`
- `ScopedIdea`
- `MarketFindings`
- `SentimentFindings`
- `FeasibilityFindings`
- `Verdict`
- `ValidationReport`

The `Verdict` model computes and overwrites model-supplied arithmetic:

$$
\operatorname{score}=2(0.30D+0.20M+0.20C+0.15F+0.15X)
$$

It also computes confidence, confidence band, fatal floors, provisional status, and the final `VALIDATE`, `NEEDS_WORK`, or `REJECT` result. The low-confidence override runs before all hard floors.

### 5. Validator Guardrails

[`src/brief_crew/validator_guardrails.py`](src/brief_crew/validator_guardrails.py) implements no-cost checks for:

- Scope completeness.
- URL closure against tool results.
- Honest failed/empty/rate-limited status handling.
- Source URL/list consistency.
- Evidence-count recomputation.
- Rubric anchor matching.
- Low-confidence language calibration.
- Provisional title and summary labels.
- Final report source closure.

The only LLM-based validator guardrail is the report citation judgement. Parallel research tasks use mechanical checks only.

### 6. Research Tools

Implemented in [`src/brief_crew/tools/`](src/brief_crew/tools/):

- `market_research.py` - Firecrawl v2 search and scrape; handles both documented result URL shapes.
- `hn_sentiment.py` - HN Algolia story search plus comment-tree retrieval; cites HN item URLs.
- `github_feasibility.py` - GitHub search with required `User-Agent`, optional token, and shared thread-safe rate limiting.

Every tool returns a JSON envelope containing `status`, `tool`, `query`, `retrieved_at`, `result_count`, `results`, and `notes`.

### 7. Validator Branch Cache

[`src/brief_crew/validator_cache.py`](src/brief_crew/validator_cache.py) implements the validator-specific cache policy:

- Market cache enabled with stricter score and freshness limits.
- Sentiment retrieval permanently disabled.
- Feasibility cache optional as a GitHub rate-limit shock absorber.
- Cache evidence supplements live research; it never skips a branch.
- Per-user opaque namespace hashing.
- Branch/category metadata filters.
- One source document per URL.
- Only captured tool-source evidence is indexable; scopes, verdicts, and reports are excluded.

Shared retrieval and indexing functions now accept the additive namespace/filter/metadata arguments needed by this path.

### 8. Event and Observability Spine

Implemented under [`src/brief_crew/events/`](src/brief_crew/events/):

- Per-run ContextVar-scoped CrewAI stream sink.
- Optional async `UIEventListener` fallback.
- Immutable versioned frame model.
- Gapless per-run sequence allocation.
- Stable node registry and visible `unattributed` quarantine node.
- Field-bounded serialization that never walks whole live CrewAI objects.
- Structured node, edge, agent, tool, LLM, token, gate, metrics, and error frames.
- 2,000-frame bounded run ring.
- 512-frame bounded subscriber queues.
- Drop, gap, and emit-error counters.
- OpenRouter token/cost accumulation by run, node, and model.

Capture callbacks do no socket or database I/O.

### 9. FastAPI and WebSocket Service

Implemented under [`src/brief_crew/service/`](src/brief_crew/service/).

Available endpoints:

```text
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

Implemented behavior includes:

- Both `brief-flow` and `idea-validator` registrations.
- Graph descriptors derived from CrewAI topology and enriched with validated fixed layout metadata.
- ETag graph versions.
- Distinct session and run IDs.
- Queued execution with configurable `RUN_CONCURRENCY` (default 1).
- Ordered replay, reconnect cursor, deduplication, and ping/pong.
- Two durable gate round trips.
- HTTP 409 for duplicate gate replies.
- Cooperative cancellation at the next CrewAI `PRE_STEP` boundary.
- NDJSON and ZIP log export.
- Health/readiness checks.
- Startup OpenRouter safety assertion.
- Synthetic service mode for no-cost integration and UI testing.

Service entry point:

```powershell
.\.venv\Scripts\serve.exe
```

### 10. Durable SQL Persistence

[`src/brief_crew/service/persistence.py`](src/brief_crew/service/persistence.py) implements CrewAI `FlowPersistence` and service storage for:

- Flow states.
- Pending feedback.
- Runs.
- Node metrics.
- Ordered frames.
- Human gates.

It supports PostgreSQL in production and SQLite for local/tests. Frame writes enter a bounded queue and are persisted by a separate batching thread, so database latency is not introduced into CrewAI event handlers.

Default local database:

```text
output/validator-studio.db
```

Production uses `DATABASE_URL` when set.

### 11. Validator Studio Frontend

[`frontend/`](frontend/) is a working Vue 3 + TypeScript + Vite + Vue Flow application, not a landing page.

Implemented UI behavior:

- Fixed live validator topology.
- Five node states: idle, running, waiting, completed, error.
- Custom animated edges driven by structured events.
- Collapsible activity/chat rail.
- Scope and verdict gate cards with editable fields.
- Launch, relaunch, cancel, and log-download controls.
- Reconnecting WebSocket client with replay and deduplication.
- Refresh recovery from saved run context and `GET /api/runs/{id}`.
- Run and per-node token/cost display.
- Error and reconnect states.
- Tablet-responsive layout.
- Keyboard labels, focus states, reduced-motion support, and Lucide icons.
- Mock fallback when no backend is reachable.
- Vite development proxies for `/api` and `/ws` to `127.0.0.1:8000`.

Run it locally:

```powershell
Push-Location frontend
npm install
npm run dev
Pop-Location
```

Then open `http://localhost:5173/` while the API runs on `http://127.0.0.1:8000`.

Production build:

```powershell
Push-Location frontend
npm run build
Pop-Location
```

## No-Cost Integration Coverage

Tests cover:

- Schemas, confidence, floors, and verdict reproducibility.
- Guardrail parsing and URL closure.
- Tool envelope handling and rate limits using mocks.
- Validator cache policy and source-only indexing.
- Three-way Flow fan-out with concurrent test doubles.
- OpenRouter model assignment and no fallback.
- Native CrewAI pause/resume through both gates.
- Event ordering, immutability, isolation, and buffer drops.
- Both graph descriptors and router routes.
- HTTP run lifecycle and WebSocket replay.
- Duplicate gate reply conflict.
- Durable recovery in a new app instance.
- Cancellation at the next step boundary.
- NDJSON/ZIP logs, health/readiness, and usage metrics.
- SQLite persistence round trips and frame ordering.

## Remaining Work and Unverified Risks

Updated 2026-08-29 after the audit-and-implement pass. Items 1-6 of the
previous list are closed; what follows is what is genuinely left.

### Needs money or a live host - no agent can close these

1. **Paid live acceptance run.** The integrated validator has never been run end
   to end against real OpenRouter, Firecrawl, Hacker News, GitHub, Pinecone and
   Cohere. Every test uses doubles. Zero-fabricated-citation closure over an
   acceptance set is therefore unverified.
2. **Live fan-out measurement (F42, Q1).** The harness is built and tested:

   ```powershell
   .\.venv\Scripts\python.exe scriptsench_fanout.py --live --yes --runs 5
   ```

   Synthetic mode measures orchestration overhead only and reports the speedup
   as **advisory**, because in that mode the ratio is a property of
   `--branch-seconds` rather than of the system. The number that does transfer
   is ~1.0-1.1 s of fixed serial overhead: clearing speedup `t` needs branch
   latency `B >= O(t-1)/(3-t)`, i.e. ~0.74 s at `t=1.8`. PRD section 14 puts
   real Firecrawl scrapes at 10-30 s, projecting 2.8x-2.9x. Two things could
   still sink it: unequal branch latencies, and GitHub's shared 10 req/min
   per-IP limit serializing the feasibility branch (R-7).
3. **Live PostgreSQL 18 exercise.** The database was upgraded from 17 to 18;
   `render.yaml` and the specs now say 18. Persistence is dialect-agnostic and
   tested on SQLite, so the untested surface is not the schema but the
   concurrency: `pending_feedback` and the gate reply both use
   `UPDATE ... WHERE ... ` + `rowcount` compare-and-set, which SQLite's
   single-writer model cannot stress. Test two processes replying to one gate.
4. **Firecrawl plan economics (Q3)** and the **Reporter/Scoper A/B tests (Q4).**

### Decisions for a human, not work to schedule

5. **The M/C/F/X rubric anchors are a derivation, not a transcription.** PRD
   section 10.2 writes out only the **Demand** ladder, and labels it
   *"Illustrative"*. The other four ladders did not exist anywhere in the repo,
   so they were derived from the PRD's stated rules and floor definitions and
   recorded as such in the `config.py` comment. They are now **binding** at 0.85
   token overlap and quoted verbatim in `tasks.yaml`. Read them before the paid
   acceptance run: if they are wrong, every verdict inherits the error and the
   guardrail enforces it confidently.
6. **Sprites (F34).** The PRD's 144 downscaled character PNGs are not in the
   repo, so this cannot be implemented as specified. The frontend ships a
   vector/icon identity instead. Either amend the criterion or supply the
   assets.
7. **Dead scaffold.** `frontend/src/components/HelloWorld.vue` and
   `src/style.css` are imported by nothing. `HelloWorld.vue` is the only
   importer of `hero.png`, which `.gitignore` was specifically amended to keep.
   Delete all three together or keep all three.

### Known gaps with a clear fix

8. **Tool payload fields are dropped before the schema sees them.** `Thread`
   now has `points` / `num_comments` and `Repo` has `archived`, but
   `tools/hn_sentiment.py` and `tools/github_feasibility.py` never read those
   fields out of the API responses they already fetch, so they stay `None`.
9. **Median source age is biased young.** `tools/market_research._publication_date`
   falls back to the *retrieval* timestamp when Firecrawl reports no publication
   date, so `Evidence.dated` can silently be "today" and the staleness
   multiplier reads optimistic. The envelope already computes a
   `used_retrieval_date` flag; it needs to carry it.
10. **Scraped page bodies chunk poorly.** `FirecrawlScrapeWebsiteTool` has no
    `result_schema`, so CrewAI hands both the agent and the capture sink
    `str(Document)` - a pydantic repr. Provenance is correct regardless; only
    chunk quality suffers. A `result_schema` or a thin subclass fixes it.
11. **`serve()` binds `127.0.0.1`.** Correct for local use, but it means the
    registered console script cannot be a container entry point without
    `HOST=0.0.0.0`. `render.yaml` sidesteps this with an explicit uvicorn
    command.
12. **Mock and live graphs use different node ids.** `MOCK_GRAPH` uses
    `scoper` / `market_analyst`; the live descriptor uses Flow method names and
    adds router/revise nodes the mock lacks. Each is self-consistent, so nothing
    breaks - but the mock is a stylisation, not a rehearsal of the live topology.
13. **An intermittent `RecursionError` in CrewAI's `Flow.resume()`** was seen
    once in ~6 gate-probe runs and never reproduced in a 10-round stress loop.
    It is in `crewai`, not this repo. Resume is what the whole Scenario C
    recovery story rests on, so watch for it before production gate work.
14. **`downloadLogs` has no test** - it calls `URL.createObjectURL`, which jsdom
    does not implement. It needs a browser-level test to be worth anything.

## Recommended Next Sequence

Everything that can be done without spending money has been done. The next
three steps all cost something, so they are ordered by what they unblock.

1. **Read the M/C/F/X rubric anchors in `config.py`** (remaining-work item 5).
   They are binding and they are a derivation. Doing this first means the paid
   run scores against a rubric you have actually approved.
2. **Push to a git remote and apply the Blueprint.** The repo has commits but no
   remote, and Render deploys from a hosted repo - this is the first hard
   blocker. On apply, check the preview *links* the hand-created
   `agentic-crew-ai-db` rather than proposing a second instance, and paste
   `VITE_API_URL` as a full origin once the API URL exists.
3. **Run one real idea through both gates with traces enabled**, and inspect
   citation closure before sharing any trace link. This closes item 1 and gives
   the first live PG 18 exercise (item 3) for free.
4. **Run the live benchmark** (item 2) once a real run is known to work.
5. **Re-test two-process gate contention against PG 18** - the one thing a real
   run does not exercise on its own.

## CrewAI Traces

For behavior debugging, enable CrewAI traces before a live run:

```powershell
crewai traces enable
crewai run
```

Traces can include prompts, task inputs/outputs, tool arguments/results, and model responses. Confirm that no secrets or personal data were processed before sharing a trace URL.
