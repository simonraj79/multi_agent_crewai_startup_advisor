# CLAUDE.md

## Read This First

This repository now contains two applications that share one Python package:

1. **Brief Crew** - the original Researcher -> Analyst -> Writer pipeline with a warm Pinecone cache.
2. **Validator Studio** - an additive six-agent startup validator with a FastAPI/WebSocket service and Vue 3 + Vue Flow UI.

Read [`AGENTS.md`](AGENTS.md) before changing CrewAI code. The specifications in [`agents/`](agents/) remain authoritative for behavior they already cover. [`PRD.md`](PRD.md) extends those specifications for Validator Studio.

[`new features/feature-list.md`](new%20features/feature-list.md) was reconciled
against source and tests on 2026-08-29 (second pass): every milestone and
feature row names the test or source path it rests on, and nothing is Complete
on a measurement nobody has taken. Read it with this file. Neither is a
substitute for re-running the suite — the counts move.

That reconciliation predates the 2026-08-30 session, which found three defects
by *running* the service (see **Deployment** and remaining-work items 10-16),
so any row it marks Complete on the service or the UI is a claim from before
those defects were known.

## Verified Baseline

Re-measured on 2026-08-30 at commit `5daf401`, working tree clean of source
changes at the time of measurement:

```text
CrewAI: 1.15.18                 Python: 3.13.5
Python tests:   378 run, 0 failures, 0 errors, 1 skipped
Frontend unit:  126 run, 0 failures, 13 files (Vitest + jsdom)
Frontend build: vue-tsc -b and Vite production build passed
Playwright E2E:   7 run, 0 failures (local SYNTHETIC=1 backend, real browser)
```

⚠️ These counts move. The Python suite has gone 65 → 295 → 341 → 378 and the
frontend 103 → 116 → 126. Re-run before quoting a number; the command is the
contract, not the figure.

> **That green was, until 2026-08-30, only ever green on a machine with a
> `.env`.** `src/brief_crew/__init__.py` calls `load_dotenv(..., override=True)`
> at import, and ~40 tests *construct* a real `LLM` or
> `FirecrawlScrapeWebsiteTool` to assert their wiring. Both demand a key in
> `__init__`. Move `.env` aside — which is exactly what a clean checkout and CI
> see — and the suite did not fail so much as fail to start:
>
> ```text
> Ran 378 tests in 5.738s
> FAILED (failures=4, errors=36, skipped=1)
> ```
>
> The runtime is the tell: **5.7s against ~37s.** Nothing ran. GitHub Actions
> had been red on every push (`5daf401`, `a3e5268`, `53afa66`) with byte-identical
> counts, while the README claimed `git clone && python -m unittest` "costs
> nothing and touches no network" — true about money, false about running.
>
> `tests/__init__.py` now `setdefault`s two obviously-fake placeholders before
> anything imports `brief_crew`. Verified both ways (378 OK with and without
> `.env`) and under a socket guard: **0 non-loopback connection attempts**. The
> suite is no-cost *and* now actually runs anywhere. A placeholder is not a
> credential — it authenticates against nothing — but if you ever add a test
> asserting key-absent behaviour, it must clear the environment itself, the way
> `tests/tools/test_github_feasibility.py` already does with
> `patch.dict(os.environ, {}, clear=True)`.

Commands used:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .

Push-Location frontend
npm run build
npm test
Pop-Location
```

The E2E suite is separate, and it will not start a backend for you.
`playwright.config.ts` deliberately has **no `webServer` entry for the Python
API**: the default Vite proxy in `vite.config.ts` points at `127.0.0.1:8000`,
which in this project is the *paid* backend, and an automated suite must not be
able to press that button. Start the free one yourself:

```powershell
$env:SYNTHETIC = "1"; $env:PORT = "8099"; .\.venv\Scripts\serve.exe

# second shell
Push-Location frontend
npx playwright test                          # all 7
npx playwright test --grep-invert @launch    # the 2 that never press Launch
Pop-Location
```

Playwright starts its own second Vite server (`e2e/vite.e2e.config.ts`, port
5273) which proxies to 8099. Five of the seven tests are tagged `@launch`;
against a deployed origin (`E2E_BASE_URL=...`) exclude them, or the smoke test
spends money.

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

## Deployment — Live

The app is deployed on Render and serving. This is new; earlier versions of
this file said the repo had no remote and treated the Blueprint as unapplied.

| | |
| --- | --- |
| UI | `https://agentic-crew-ai-web.onrender.com` — static site, free plan |
| API | `https://agentic-crew-ai-api.onrender.com` — web service, python, **starter**, **singapore** |
| DB | `agentic-crew-ai-db` — basic_256mb, PostgreSQL 18, singapore. Pre-existing and **reused**, not recreated by the apply |
| Repo | `https://github.com/simonraj79/multi_agent_crewai_startup_advisor` (**public**), branch `main`, `autoDeploy: yes` on both services |
| Commit | `5daf401` — *inferred*, not read back: local `main`, `origin/main` and `autoDeploy: yes` agree, and the live CORS behaviour requires `53afa66` or later. The service exposes no version endpoint |

Verified live on 2026-08-30 by querying the deployed API directly:

- `GET /readyz` → `"storage":{"backend":"postgresql"}`.
- `GET /api/workflows/idea-validator/graph` → **14 nodes, 16 edges**.
- Preflight `OPTIONS /api/workflows` → **200** for
  `Origin: https://agentic-crew-ai-web.onrender.com`, **400** for a
  disallowed origin.
- `wss://…/ws?session_id=…&run_id=…` → **HTTP 101** upgrade.
- `GET https://agentic-crew-ai-web.onrender.com/` → 200.

What is **not** verified is anything that costs money: no run has been launched
against the deployed API. See remaining-work item 1.

> **Probing `/ws` by hand.** `run_id` is a **required** query parameter with no
> default, so a handshake that omits it is rejected by FastAPI validation
> *before* `accept()` and comes back as a bare **403** carrying Cloudflare's
> headers — which reads exactly like an edge/bot block and is not. Pass any
> syntactically valid `run_id`: an unknown one upgrades to 101 and is then
> closed with 4404, which is enough to prove the socket end to end at zero
> cost. Note the app's custom close codes (4404 / 4403 / 4400) did **not**
> survive the Render edge in that probe — the client saw 1005. Harmless today
> only because `studioApi.ts` never reads a close code.

### Traps that were hit for real

Each of these cost a debugging cycle. They are recorded because none is
discoverable from the code.

1. **The database's `ipAllowList` is empty.** So `DATABASE_URL` must be the
   **internal** connection string, and the API service must stay in
   `singapore` to reach it. `render.yaml` (line ~29) and `docs/deploying.md`
   both assert that the live database "already has an allow list" and that
   declaring one would overwrite it — **they are wrong**, and the comment
   reads as reassurance about a control that does not exist.
2. **`VITE_API_URL` is a Vite *build-time* variable.** Changing it does nothing
   until the static site is redeployed. It must be a **full origin including
   `https://`**: `fromService … property: host` yields a bare hostname, which
   resolves as a relative path, breaks `/ws`, and drops the client into its
   **silent scripted mock** — a UI that renders a complete, entirely fabricated
   run with no error anywhere on screen. That failure mode is the reason
   `frontend/e2e/studio.spec.ts` has a test asserting the transport is live.
3. **Render snapshots a deploy's environment when the deploy is *created*, not
   when the container starts.** Adding `CORS_ALLOW_ORIGINS` to an existing
   service therefore needed a *second* deploy to take effect. Worse: after that
   deploy reports `live`, the edge can keep routing to the draining instance
   for roughly a minute, so preflights keep returning 400 — a phantom CORS bug
   that fixes itself if you wait.
4. **`vue-tsc -b` typechecks `tests/` as well as `src/`, and `-b` is
   incremental.** A strict-null error in a newly added *test* file failed the
   **static site** build, and a warm `.tsbuildinfo` can skip the new file so it
   passes locally and fails on Render. Verify with `vue-tsc -b --force` before
   trusting a green local build. This is what commit `5daf401` is.
5. **`.gitignore` matched `.env` and nothing near it.** The rules were `.env`,
   `.env.local`, `.env.*.local` — so a *backup* was not covered. A tooling step
   moved `.env` aside and left `.env.ci-bak`, seven live keys, untracked in the
   root of a **public** repo, one `git add -A` from publication. Now `.env.*`
   with `!.env.example`. The lesson is the method, not the rule: this was found
   by running `git check-ignore -v` against the actual filenames, and reading
   `.gitignore` would have shown three reassuring `.env` lines. Check the path,
   never the pattern.

   The same class of hazard is still open: **`docs/` is untracked but NOT
   ignored**, so `git add -A` publishes it — and its own `licensing.md` raises
   an unresolved third-party-IP question while `preflight.md` carries live
   account state. Decide, or ignore it; do not leave it one command away.

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
- Rubric anchor matching (`anchor_problems`: the `anchor_matched` text must be
  the anchor for that dimension at that score).
- Rubric **evidence support** (`score_support_problems` / `rubric_support`: the
  counted evidence must be able to carry the score claimed). Anchor matching
  checks the *wording*; this checks the *findings*, so a Synthesist cannot quote
  the D=5 anchor verbatim over two stale threads. Scores are bounded from above
  everywhere and from below only at levels 0 and 1, which are the two levels
  where a low score is itself a strong claim. Judgement clauses are never
  enforced.
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
- Gate replies over **both** HTTP and the WebSocket, sharing one
  compare-and-set path, with the inbound socket message bounded by
  `WS_MAX_MESSAGE_BYTES` / `WS_MAX_GATE_FIELDS` / `WS_MAX_GATE_FIELD_CHARS`.
- Two durable gate round trips.
- A gate payload split into editable `fields` and read-only `derived` values.
  At the verdict gate every `Verdict` key is derived, because seven of them are
  arithmetic the schema recomputes and discards and the rest are inputs the
  guardrails bind to the rubric and to real tool URLs — neither survives a text
  box. `fields` is *pruned* rather than annotated, so a stale client cannot go
  on offering an edit the server would throw away. The operator's lever is
  `decision=revise` plus feedback.
- HTTP 409 for duplicate gate replies.
- A gate reply that is accepted durably but cannot start its resume is **rolled
  back**, not left committed: `persistence.reopen_gate()` is a compare-and-set
  in the opposite direction that clears `answered_at`, restores the F03 watch
  state and re-emits `GATE_OPEN`. The transport answers **503**, not 500 — the
  reply was well formed and resending it works.
- Cooperative cancellation at the next CrewAI `PRE_STEP` boundary.
- NDJSON and ZIP log export.
- Health/readiness checks.
- Startup OpenRouter safety assertion.
- CORS middleware driven by `CORS_ALLOW_ORIGINS` in `config.py`:
  comma-separated origins, **empty default, so it fails closed**; a malformed
  entry is refused *at import* with the corrected string in the message rather
  than normalised away; `CORS_ALLOW_CREDENTIALS` is a fixed `False`, which is
  what makes the `"*"` escape hatch survivable. **It does not govern `/ws`** —
  browsers do not apply CORS to a WebSocket handshake and Starlette passes
  non-HTTP scopes straight through. See remaining-work item 13.
- Synthetic service mode for no-cost integration and UI testing, selected by
  `SYNTHETIC=1` through `app_from_env()`.

Service entry point:

```powershell
.\.venv\Scripts\serve.exe                      # paid runners
$env:SYNTHETIC = "1"; .\.venv\Scripts\serve.exe  # no-cost doubles
```

`serve()` hands uvicorn a factory **by name**, and a string factory cannot
receive kwargs, so for a while the console script could only ever build the
paid runners — anyone starting the service to look at the UI spent real money
the moment they pressed Launch. `app_from_env()` is the indirection that fixes
that. `HOST` and `PORT` are read from the environment (see item 8).

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
- Five node states: idle, running, waiting, completed, error. The `waiting`
  state is set by `applyGate`, not by the event type — see item 12.
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
- Run completion driven by `details.status` on the `RUN_STATE` frame, with a
  fallback to `event_type` — see item 20 in the closed ledger for why both.
- Mock fallback when no backend is reachable. It is **silent**: there is no
  on-screen indication beyond a "Mock mode" label, so a misconfigured
  `VITE_API_URL` produces a convincing fabricated run rather than an error.
- Vite development proxies for `/api` and `/ws` to `127.0.0.1:8000` — the
  **paid** backend. `e2e/vite.e2e.config.ts` is a second, separate dev server
  that points at the free one on 8099 instead.

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
- Gate replies over the WebSocket, including a duplicate, a malformed message
  and a late reply after expiry.
- The gate `fields` / `derived` split, server and client.
- Rubric anchor text *and* rubric evidence support for all five ladders.
- Brief Crew regression: the cache router's contract, both statically visible
  branches, `persist`, the tool surfaces, `run_crew()` and `kickoff()`.
- The fan-out benchmark harness itself (`tests/perf/`, 58 tests), which is not
  the measurement — see remaining-work item 2.
- The gate-reply/resume race, including the settling window, the `reopen_gate`
  rollback and the 503 (`tests/service/test_gate_resume_race.py`, 11 tests).
- The CORS contract: origin parsing, the fail-closed empty default, the
  startup refusal of a malformed origin, and the fact that `/ws` is **not**
  covered (`tests/service/test_cors.py`, 16 tests).
- `serve()`'s environment handling, so `SYNTHETIC=1` really does select the
  no-cost runners (`tests/service/test_serve_env.py`, 5 tests).
- Frontend: Vitest + jsdom over the mock graph against the live descriptor,
  edge animation, frame handling, gate cards and derived fields, run recovery,
  the router and quarantine nodes, the API client and log download.
- The `RUN_STATE` frame shape, pinned on **both** sides against one committed
  fixture generated by the real serializer, so backend and client cannot drift
  apart again: `tests/events/test_run_state_status.py` (5 tests),
  `frontend/tests/fixtures/backendRunStateFrames.json`, and
  `frontend/tests/realFrameShape.spec.ts` (6 tests).
- A paused gate node reporting `waiting` rather than `idle`
  (`frontend/tests/gateNodeWaiting.spec.ts`, 4 tests). All four fail if the
  line is reverted.

### End-to-end, in a real browser

`frontend/e2e/studio.spec.ts` (7 tests, Playwright + Chromium) drives the app
against its own `SYNTHETIC=1` backend over a **real** WebSocket: the fixed
topology, live-versus-mock transport detection, the full operator journey
through both durable gates to completion, the waiting gate node, the verdict
gate's read-only fields, a `revise` reply at the scope gate, and run recovery
across a page reload.

This is the layer that found all three of the 2026-08-30 defects. It is still
no-cost — but it is a *synthetic* backend, so it proves the plumbing, not the
agents. Note in particular that `SyntheticValidatorRunner` does not model
`revise` at all (item 15), so the revise loop is exercised only as far as "the
reply is accepted and the run keeps going".

## Remaining Work and Unverified Risks

Updated 2026-08-30, after deploying the service and then finding three defects
by running it. The deployment closed one blocker outright and *half* of another;
it also opened seven new gaps. Numbering is continuous and has shifted.

### Needs money or a live host - no agent can close these

1. **Paid live acceptance run. Still completely open.** The integrated validator
   has **never** been run end to end against real OpenRouter, Firecrawl, Hacker
   News, GitHub, Pinecone or Cohere. Every Python test, every frontend test and
   every one of the seven E2E tests uses doubles or the synthetic runner.
   Zero-fabricated-citation closure over an acceptance set is unverified.
   Deploying the service did not change this in any way: the live checks in
   **Deployment** above are all `GET`s, and no run has been launched against
   the deployed API.

   **There is now a standing recommendation against doing this yet.** The
   uncommitted `docs/rubric-review.md` is an independent adversarial pass over
   `RUBRIC_ANCHORS` whose verdict is *"No. Do not spend money on a live
   acceptance run against this rubric as it stands."* It reports 13 findings —
   2 Critical, 3 High — each with a worked scenario executed against the
   shipped `Verdict` model and `rubric_problems()`, not against paper
   arithmetic. Spot-checked at head: its two criticals both still hold, because
   `validator_guardrails.py` still reads `zero_ok = usable >= 1 and
   problems == 0` (D) and `zero_ok = sources >= 1` (M), and the last commit to
   touch the rubric (`73c6375`) predates the review. **None of its findings
   have been implemented.** See item 5.
2. **Live fan-out measurement (F42, Q1).** The harness is built and tested
   (`scripts/bench_fanout.py`, `scripts/perf_arms.py`, `scripts/perf_metrics.py`,
   58 tests in `tests/perf/`):

   ```powershell
   .\.venv\Scripts\python.exe scripts\bench_fanout.py --live --yes --runs 5
   ```

   Synthetic mode measures orchestration overhead only and reports the speedup
   as **advisory**, because in that mode the ratio is a property of
   `--branch-seconds` rather than of the system. The number that does transfer
   is ~1.0-1.1 s of fixed serial overhead: clearing speedup `t` needs branch
   latency `B >= O(t-1)/(3-t)`, i.e. ~0.74 s at `t=1.8`. PRD section 14 puts
   real Firecrawl scrapes at 10-30 s, projecting 2.8x-2.9x. Two things could
   still sink it: unequal branch latencies, and GitHub's shared 10 req/min
   per-IP limit serializing the feasibility branch (R-7).
3. **Live PostgreSQL 18 exercise — now half closed.** `metadata.create_all()`
   has run clean against PG 18 in production for the first time: the deployed
   API answers `/readyz` with `"backend":"postgresql"`, which it cannot do
   without having created its schema. Every test still runs on SQLite, so that
   is one DDL pass on one dialect, not coverage.

   **Still open, and one instance cannot close it:** the concurrency.
   `pending_feedback` and the gate reply both use `UPDATE ... WHERE ...` +
   `rowcount` compare-and-set, and so does the new `reopen_gate()` rollback in
   the opposite direction. SQLite's single-writer model cannot stress any of
   them. Test two processes replying to one gate.
4. **Firecrawl plan economics (Q3)** and the **Reporter/Scoper A/B tests (Q4).**

### Decisions for a human, not work to schedule

5. **The rubric anchors have been audited, adversarially reviewed, and still
   read by no human — and the review says stop.** This is now the single most
   urgent item in this file, because the service is deployed and standing by to
   score a real idea against a rubric nobody has approved.

   Since the last handoff an independent agent produced
   `docs/rubric-review.md` (uncommitted; see item 17). It does **not** close
   this item — it self-identifies as *"Reviewer: independent agent"*, and what
   item 5 asks for is a **human**. What it does do is make the item worse:
   it concludes *"do not spend money on a live acceptance run against this
   rubric as it stands"* and lists 13 defects, of which these three decide the
   answer:

   - **F1 (Critical, X).** `FLOOR_ALREADY_FREE` is counted only over GitHub
     repositories marked `SOLVES_ENTIRELY`. A free *product* — Google Calendar,
     a free tier — that already does the whole job cannot reach X=0; the
     ladder's own words put it at X=3, which clears `min >= 3`. Measured:
     composite 9.4, confidence 0.90, `VALIDATE`, zero guardrail complaints.
     PRD §10.2 calls this floor "the most valuable output this system
     produces".
   - **F2 (Critical, D).** `zero_ok = usable >= 1 and problems == 0` means one
     on-topic HN comment in which nobody states a problem fires
     `FLOOR_NO_DEMAND`. Measured: a **final, non-provisional** `REJECT — no
     demand` at confidence 0.60 over five web pages, four repos and one
     opinion. The confidence override is structurally unable to intervene.
   - **F4 (High, F and X).** Three of the four floors and the entire VALIDATE
     gate turn on labels the *tools* pre-compute by substring match, shipped in
     the envelope under the same field names the schema uses — so copying them
     is the cheapest valid output a cheap-tier branch agent can produce.
     `_relevance` assigns `SOLVES_ENTIRELY` on 75% query-word overlap;
     `_classify` assigns `PAYS` to any comment containing `pay`.

   The review is emphatic that the *machinery* held under attack — the level-1
   reservation, the ceiling bounds, anchor separation, the recomputed counts,
   the ordering of the confidence override — and says fixing five things flips
   its answer to yes. Read it before reading the eight anchors below; it is
   longer and more specific than this summary.

   The rest of this item is the previous handoff's note, still accurate:

   PRD §10.2 writes out only the **Demand** ladder and labels
   it *"Illustrative"*; M/C/F/X never existed anywhere in the repo and were
   derived from the PRD's stated rules, weights, floors and dimension questions.
   An audit on 2026-08-29 found six unsound anchors (including three in the
   PRD's own Demand ladder — see PRD §10.2's correction block) and rewrote all
   five ladders. They are covered by tests, **binding** at 0.85 token overlap in
   `anchor_problems`, bounded against the counted evidence by
   `score_support_problems`, and quoted verbatim into `tasks.yaml`. What is
   *not* true is that anyone has read them. Audited is not reviewed: a
   derivation error is a judgement nobody made, and it cannot be found by
   running the suite.

   **Read `RUBRIC_ANCHORS` in `config.py` before the paid acceptance run.** These
   eight are what the audit itself remained unsure of, in the order a reviewer
   should take them:

   1. **F=0** — now *"repositories returned, none marked SOLVES_ENTIRELY or
      PARTIAL"*. It over-fires for a v1 whose stack is so ordinary nobody
      publishes it, and it triggers `FLOOR_NOT_BUILDABLE`. Over-firing was
      chosen deliberately: the alternative wording rested on no schema field at
      all, and an unreachable floor is worse than a cautious one.
   2. **C=0 vs C=2 splits on `vendor_owned`** — the only structured fact
      `Competitor` carries besides pricing. The *definition* of vendor-owned
      written into `market_task` is the auditor's, not the spec's.
   3. **X=3/4/5's "covers most of the core job" vs "a separable part"** — a
      bounded judgement, not a count, and the hinge the whole X ladder turns on.
      `rubric_support` drops it rather than enforcing it.
   4. **D=1 drops the PRD's "<3 usable threads"** — an amendment to the only
      ladder the PRD ever wrote. Rationale in PRD §10.2: it duplicates
      `evidence_thin` and collided with D=2.
   5. **D=2's 24-month boundary replaces the PRD's 36 months**, to close the
      dead band the PRD ladder left between D=2 and D=3.
   6. **M=0 is read as "no nameable buyer"**, dropping the PRD floor's "no
      money" conjunct on the grounds that the dimension's question is *"can you
      name whose?"*.
   7. **D=0 vs D=1** — this one has moved. It was unrecomputable because
      `compute_evidence_counts` had no usable-thread counter; a
      `sentiment_usable_threads` counter (`classification != "OFF_TOPIC"`) has
      since landed in `validator_guardrails.py`, and `rubric_support` now makes
      D=0 mechanical (`zero_ok = usable >= 1 and problems == 0`) and D=1
      mechanical (`one_ok = usable == 0`). The **classification itself** is still
      the Sentiment Analyst's judgement, so the REJECT floor now rests on
      labelling rather than on arithmetic. Verify this against the file rather
      than against this list — it was landing while this was written.
   8. **F=5's "together cover the separable parts of the scoped v1"** —
      inherited from the derivation, still judgement, still unenforced.
6. **Sprites (F34).** The PRD's 144 downscaled character PNGs are not in the
   repo, so this cannot be implemented as specified. The frontend ships a
   vector/icon identity instead: no per-agent palette, no hash-based assignment,
   no walk cycle. Verified still absent — nothing under `frontend/src` mentions
   a sprite. Either amend the criterion or supply the assets.
7. **Dead scaffold — a five-file cluster, not three.** Verified again on
   2026-08-30, still present, still unreferenced:

   - `frontend/src/components/HelloWorld.vue` — imported by nothing.
   - `frontend/src/style.css` — imported by nothing. (`main.ts` imports
     `@vue-flow/core/dist/style.css`, which is a different file; that is why
     this one looks used to a careless grep.)
   - `frontend/src/assets/hero.png`, `vite.svg` and `vue.svg` — `HelloWorld.vue`
     is the **only** importer of all three.

   Plus a sixth artefact: `.gitignore` carries an explicit exception
   (`!frontend/src/assets/**/*.png`, with a comment naming `HelloWorld.vue`)
   added purely to keep `hero.png` alive against the global `*.png` rule.
   Delete all five together and drop the exception, or keep all of it.

### Known gaps with a clear fix

8. **`serve()` binds `127.0.0.1`.** Still true, and still correct for local
   use, but it means the registered console script cannot be a container entry
   point without `HOST=0.0.0.0`. `service/app.py` reads
   `os.getenv("HOST", "127.0.0.1")` and `os.getenv("PORT", "8000")`, so both
   are environment-configurable, and `SYNTHETIC=1` now selects the no-cost
   runners through `app_from_env()` (item 22). `render.yaml` still sidesteps
   the binding with an explicit uvicorn command rather than using the script.
9. **An intermittent `RecursionError` in CrewAI's `Flow.resume()`** was seen
   once in ~6 gate-probe runs and never reproduced in a 10-round stress loop.
   It is in `crewai`, not this repo. Resume is what the whole Scenario C
   recovery story rests on, so watch for it before production gate work.
   *Unverified in this pass — reproducing it needs live gate probes.*
#### New in this pass — found by running the deployed app, not by reading it

None of items 10-16 is caught by any test, and none was visible locally.

10. **The header says "Offline" whenever no run is in flight.** `App.vue`
    renders the `connection` ref directly, and that ref tracks the
    **WebSocket**, which only exists during a run: it initialises to
    `'offline'` and `resetRun()` puts it back. So "the backend is down" and
    "you have not launched anything yet" are the same word on the first thing
    a visitor reads. Nothing polls API reachability. This is what makes the
    silent mock fallback (Deployment trap 2) so hard to spot.

    **Status: an uncommitted fix was in the working tree when this was
    written** — a `connectionLabel` computed in `App.vue` that reports the
    probed transport (`ready` / `connecting`) while nothing is streaming and
    hands back to the socket once a run is in flight, plus assertions in
    `frontend/e2e/studio.spec.ts`. That is a *label* fix: it stops the console
    lying on load, and it still does not poll the API, so a backend that dies
    between page load and Launch will read `ready`. Verify against `App.vue`
    rather than against this note, and re-run both suites — the measured counts
    in **Verified Baseline** predate it.
11. **The idea textarea resets after a reload even though the run recovers.**
    `useValidatorRun.ts` recovers run context from `localStorage` and
    `GET /api/runs/{id}`, but `idea` is a plain `ref` seeded with a hardcoded
    default and is never assigned anywhere. Refresh mid-run and the graph and
    the gates come back correctly above a text box that has silently reverted
    to *"An AI tool that turns Figma files into production React"*.
12. **`applyNodeState`'s `WAITING` branch is dead code against the real
    backend.** It tests `frame.event_type.includes('WAITING')`, and **no member
    of `UIEventType` contains that substring** — the only `WAITING` in
    `events/models.py` is inside a comment. The branch does still fire for the
    mock transport, which emits a `NODE_WAITING` the server never sends, which
    is exactly how it survived. `applyGate` now sets the waiting node (item
    21); the unreachable branch was left in place.
13. **`/ws` has no `Origin` check.** `CORS_ALLOW_ORIGINS` does not reach it:
    browsers do not apply CORS to a WebSocket handshake and Starlette passes
    non-HTTP scopes through. The socket does require a `run_id` that exists and
    a matching `session_id`, so an attacker needs a run identifier to get
    anything, but nothing stops a page on any origin from opening the socket.
14. **The graph `ETag` is set and never honoured.** `app.py` writes
    `ETag: "{graph.version}"` on the graph response and nothing anywhere reads
    `If-None-Match`. Confirmed against the deployed API: a conditional `GET`
    carrying the exact ETag it had just returned came back **200**, not 304.
    The header is decoration.
15. **`SyntheticValidatorRunner` does not model `revise`.** `resume()` branches
    on `context.metadata["synthetic_stage"]` only and never reads `decision`
    from the payload, so a `revise` at the scope gate advances to the verdict
    gate exactly as `approve` would. The revise loop is therefore **never
    exercised end to end** by anything — not the E2E suite, not the service
    tests. The `@launch` test named "accepts a Revise reply at the scope gate
    and keeps the run going" is honestly titled: it proves the reply is
    accepted, not that anything loops back.
16. **`render.yaml` hardcodes a value that cannot be known when it is written,
    and asserts a control that does not exist.** `CORS_ALLOW_ORIGINS` is
    committed as `https://agentic-crew-ai-web.onrender.com` — a URL that only
    exists *after* the static site is created, so a first apply into a
    differently-named service ships a wrong value that fails closed and looks
    like missing middleware. Separately, its `ipAllowList` comment (and
    `docs/deploying.md` around line 90) says the live database "already has an
    allow list"; **it is empty**. See Deployment trap 1.
17. **`docs/` exists locally and is deliberately not committed.** It is *not*
    gitignored — it is simply untracked, which means a `git add -A` would
    publish it. Four files: `licensing.md`, `deploying.md`, `preflight.md`,
    `rubric-review.md`. Two reasons to hold them:

    - `licensing.md` raises an **unresolved third-party-IP question** about the
      repo's own contents (`agents/workflow.md` §3-§4 and `agents/patterns.md`
      §12 reproduce a named person's lecture deck at length; PRD §8
      reverse-engineers a third-party frontend with a Lift/Adapt/Drop plan
      against a licence nobody has recorded). It also notes the repo has no
      `LICENSE` at all, which for a **public** repo means all rights reserved.
    - `preflight.md` documents live account state — the credential regime, the
      OpenRouter catalogue checked against live prices, and spend bounds.

    Decide publish-or-not deliberately. Do not let it happen by accident.

### Closed since the last handoff — verified, not assumed

Kept as a short ledger so nobody reopens them from an old note.

18. **The stale schema docstrings are gone.** `Thread.points` /
    `num_comments` and `Repo.archived` no longer claim the tool envelopes "do
    not carry them yet"; the comments now explain why each is nullable and how
    the ladders read a `None`. Verified by reading
    `schemas/validator.py:175-220`. This was item 10 in the previous list.
19. **A gate reply can no longer wedge a run permanently.** `_mark_pending`
    published the gate — durable row, WAITING status, `GATE_OPEN` frame — from
    inside `_execute` *before* the worker returned, so a reply landing in that
    window hit `_submit`'s "already executing" guard. `answer_gate` had already
    done the durable compare-and-set and cleared `pending_gate`, so the run sat
    RUNNING forever with a 409 on every retry, **and it survived a process
    restart**. Reproduced on 3 of ~16 live runs; polling for
    `status == waiting` did not avoid it, because WAITING is set before the
    future settles. `_submit` now waits out the settling future **outside**
    `RunRegistry._lock` — inside would deadlock, because a frame emitted from
    `_execute`'s tail reaches `_note_persistence_error`, which takes that lock
    — bounded by `RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS` in `config.py`. A resume
    that is still refused rolls back through `persistence.reopen_gate()` and
    answers **503**. `tests/service/test_gate_resume_race.py`, 11 tests.
20. **The UI finishes a real run.** `events/serializer.py` emitted `RUN_STATE`
    for flow start and finish carrying only `{inputs}` / `{result}` — no
    `status` — while `applyRunState` read `details.status` alone, and nothing
    polls during a run. Every test double happened to send a status, and every
    frontend spec asserted against `event_type` values the backend **never
    emits** (`RUN_COMPLETED` and friends are not members of `UIEventType`), so
    116 green tests could not see it. Both drafts now carry `status`, both
    synthetic runners match the real shape, the client falls back to
    `event_type`, and the two sides are pinned by a committed fixture generated
    from the real serializer.
21. **A paused gate node shows as `waiting`.** `applyGate` sets it. Previously
    it set only the *run* status, and the node branch that would have done it
    was unreachable (item 12), so `confirm_scope` looked exactly like
    `revise_scope` at the moment the operator was being asked. The asymmetry
    was the tell: `gate_closed` had always set the same node to `completed`.
22. **`serve()` can run no-cost.** It hands uvicorn a factory *by name*, and a
    string factory drops kwargs, so the console script could previously only
    build the paid runners — anyone starting the service to look at the UI
    spent real money the moment they pressed Launch. `app_from_env()` reads
    `SYNTHETIC`. `tests/service/test_serve_env.py`, 5 tests.
23. **CORS middleware exists.** Invisible locally, where Vite's proxy makes
    everything same-origin; fatal in production, where the static site is a
    separate origin. `tests/service/test_cors.py`, 16 tests.
24. **Tool payload fields now reach the schema.** `tools/hn_sentiment.py` reads
    `points` / `num_comments` off the Algolia story record (`_story_metric`, and
    it notes unreported ones), and `tools/github_feasibility.py` reads
    `archived` (`_archived`, tri-state, with a note when GitHub reported none).
25. **Median source age is no longer biased young.** `Evidence` carries
    `dated_is_retrieval_time`, `market_research` sets it on every row that fell
    back to the retrieval timestamp, and
    `validator_guardrails._market_source_age_months` returns `None` for those
    rows so they cannot read as fresh.
26. **Scraped page bodies chunk on structure.**
    `crews/brief_crew/scrape_tool.py` subclasses `FirecrawlScrapeWebsiteTool`
    with a `ScrapedPage` `result_schema`, so what reaches the agent and the
    capture sink is a JSON envelope carrying the page markdown verbatim rather
    than `str(Document)`.
27. **Mock and live graphs agree.** `frontend/src/data/mockGraph.ts` now uses
    the live Flow method ids and carries the routers, the revise loops and the
    quarantine node; `frontend/tests/mockGraph.spec.ts` asserts the node list
    and edge list against the live descriptor, in order.
28. **`downloadLogs` is tested.** jsdom 30 implements the blob URL store, so
    `frontend/tests/downloadLogs.spec.ts` exercises minting, revoking,
    percent-encoding, the ZIP name and the failure paths for real; only the
    anchor `click` is stubbed.
29. **WebSocket gate replies** land through the same compare-and-set path as
    HTTP (`service/app.py::handle_gate_reply`), bounded by the three `WS_*`
    limits, and covered by `tests/integration/test_ws_gate_replies.py` (**10**
    tests — the previous handoff said 7) plus three `studioApi.spec.ts` cases.
30. **Brief Crew has a regression test.** `tests/test_brief_crew_regression.py`
    (23 tests, re-counted) covers the Track A/B behaviour the platform rules
    forbid regressing.

## Recommended Next Sequence

The deployment blocker is gone: the repo has a remote, the Blueprint is applied,
and both services are live. What is left is one decision, then money.

1. **Read `docs/rubric-review.md`, then read all five ladders in
   `RUBRIC_ANCHORS`** (remaining-work item 5). This is a decision only a human
   can make, and it is now blocking: the service is deployed and one Launch away
   from scoring a real idea against a rubric that an adversarial review says is
   not ready. Take F1, F2 and F4 first — two Criticals and the tool-label
   coupling — and decide each of *accept / fix / accept-with-eyes-open*. Fixing
   them is a source change with tests already in place to catch it
   (`tests/validator/test_crews.py` and `test_guardrails.py` assert anchor text
   and support bounds directly), so an anchor edit will surface there rather
   than silently.
2. **Settle `docs/` and the licence** (item 17) before anyone else reads the
   public repo. It is untracked, not ignored, so this is one careless `git add
   -A` away from being decided for you. The repo is public with no `LICENSE`,
   which means all rights reserved — almost certainly not the intent.
3. **Run one real idea through both gates on the deployed service, with traces
   enabled**, and inspect citation closure before sharing any trace link. This
   closes item 1 and puts real concurrent load on PG 18 (item 3). Do it only
   after step 1: the whole point of a paid acceptance run is the verdict, and a
   verdict against an unapproved rubric buys nothing.
4. **Run the live benchmark** (item 2) once a real run is known to work.
5. **Re-test two-process gate contention against PG 18** — the one thing a
   single real run cannot exercise, and now the *only* untested half of item 3.
   The `reopen_gate()` rollback added this pass is a second compare-and-set that
   has never met a concurrent writer.

Cheap cleanups that need no decision and no money: items 10-16. Item 14 (the
unhonoured ETag) and item 12 (the dead `WAITING` branch) are each a few lines.

## CrewAI Traces

For behavior debugging, enable CrewAI traces before a live run:

```powershell
crewai traces enable
crewai run
```

Traces can include prompts, task inputs/outputs, tool arguments/results, and model responses. Confirm that no secrets or personal data were processed before sharing a trace URL.
