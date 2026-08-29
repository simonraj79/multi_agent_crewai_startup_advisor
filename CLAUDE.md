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

## Verified Baseline

Verified on 2026-08-29:

```text
CrewAI: 1.15.18
Python tests:   341 run, 0 failures, 0 errors, 1 skipped
Frontend tests: 116 run, 0 failures, 11 files (Vitest + jsdom)
Frontend build: vue-tsc and Vite production build passed
```

⚠️ These counts move. The suite grew 295 → 341 Python and 103 → 116 frontend
during a single documentation pass. Re-run before quoting a number; the command
is the contract, not the figure.

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
- Gate replies over the WebSocket, including a duplicate, a malformed message
  and a late reply after expiry.
- The gate `fields` / `derived` split, server and client.
- Rubric anchor text *and* rubric evidence support for all five ladders.
- Brief Crew regression: the cache router's contract, both statically visible
  branches, `persist`, the tool surfaces, `run_crew()` and `kickoff()`.
- The fan-out benchmark harness itself (`tests/perf/`), which is not the
  measurement — see remaining-work item 2.
- Frontend: Vitest + jsdom over the mock graph against the live descriptor,
  edge animation, frame handling, gate cards and derived fields, run recovery,
  the router and quarantine nodes, the API client and log download.

## Remaining Work and Unverified Risks

Updated 2026-08-29 after the audit-and-implement pass. Items 1-6 of the
previous list are closed; what follows is what is genuinely left.

### Needs money or a live host - no agent can close these

1. **Paid live acceptance run.** The integrated validator has never been run end
   to end against real OpenRouter, Firecrawl, Hacker News, GitHub, Pinecone and
   Cohere. Every test uses doubles. Zero-fabricated-citation closure over an
   acceptance set is therefore unverified.
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
3. **Live PostgreSQL 18 exercise.** The database was upgraded from 17 to 18;
   `render.yaml` and the specs now say 18. Persistence is dialect-agnostic and
   tested on SQLite, so the untested surface is not the schema but the
   concurrency: `pending_feedback` and the gate reply both use
   `UPDATE ... WHERE ... ` + `rowcount` compare-and-set, which SQLite's
   single-writer model cannot stress. Test two processes replying to one gate.
4. **Firecrawl plan economics (Q3)** and the **Reporter/Scoper A/B tests (Q4).**

### Decisions for a human, not work to schedule

5. **The rubric anchors have been audited, repaired and tested — and still
   read by no human.** PRD §10.2 writes out only the **Demand** ladder and labels
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
7. **Dead scaffold.** `frontend/src/components/HelloWorld.vue` and
   `frontend/src/style.css` are imported by nothing. `HelloWorld.vue` is the
   only importer of `frontend/src/assets/hero.png`, which `.gitignore` was
   specifically amended to keep. Verified still true. Delete all three together
   or keep all three.

### Known gaps with a clear fix

8. **`serve()` binds `127.0.0.1`.** Correct for local use, but it means the
   registered console script cannot be a container entry point without
   `HOST=0.0.0.0` (`service/app.py` reads `os.getenv("HOST", "127.0.0.1")`).
   `render.yaml` sidesteps this with an explicit uvicorn command.
9. **An intermittent `RecursionError` in CrewAI's `Flow.resume()`** was seen
   once in ~6 gate-probe runs and never reproduced in a 10-round stress loop.
   It is in `crewai`, not this repo. Resume is what the whole Scenario C
   recovery story rests on, so watch for it before production gate work.
   *Unverified in this pass — reproducing it needs live gate probes.*
10. **Stale docstrings in the schemas.** `Thread.points` / `num_comments` and
    `Repo.archived` still carry comments saying the tool envelopes "do not carry
    them yet". The tools now populate all three (item 11 below); the comments
    were not updated with them.

### Closed since the last handoff — verified, not assumed

Kept as a short ledger so nobody reopens them from an old note.

11. **Tool payload fields now reach the schema.** `tools/hn_sentiment.py` reads
    `points` / `num_comments` off the Algolia story record (`_story_metric`, and
    it notes unreported ones), and `tools/github_feasibility.py` reads
    `archived` (`_archived`, tri-state, with a note when GitHub reported none).
12. **Median source age is no longer biased young.** `Evidence` carries
    `dated_is_retrieval_time`, `market_research` sets it on every row that fell
    back to the retrieval timestamp, and
    `validator_guardrails._market_source_age_months` returns `None` for those
    rows so they cannot read as fresh.
13. **Scraped page bodies chunk on structure.**
    `crews/brief_crew/scrape_tool.py` subclasses `FirecrawlScrapeWebsiteTool`
    with a `ScrapedPage` `result_schema`, so what reaches the agent and the
    capture sink is a JSON envelope carrying the page markdown verbatim rather
    than `str(Document)`.
14. **Mock and live graphs agree.** `frontend/src/data/mockGraph.ts` now uses
    the live Flow method ids and carries the routers, the revise loops and the
    quarantine node; `frontend/tests/mockGraph.spec.ts` asserts the node list
    and edge list against the live descriptor, in order.
15. **`downloadLogs` is tested.** jsdom 30 implements the blob URL store, so
    `frontend/tests/downloadLogs.spec.ts` exercises minting, revoking,
    percent-encoding, the ZIP name and the failure paths for real; only the
    anchor `click` is stubbed.
16. **WebSocket gate replies** land through the same compare-and-set path as
    HTTP (`service/app.py::handle_gate_reply`), bounded by the three `WS_*`
    limits, and covered by `tests/integration/test_ws_gate_replies.py` (7
    tests) plus three `studioApi.spec.ts` cases.
17. **Brief Crew has a regression test.** `tests/test_brief_crew_regression.py`
    (23 tests) covers the Track A/B behaviour the platform rules forbid
    regressing.

## Recommended Next Sequence

Everything that can be done without spending money has been done. The next
three steps all cost something, so they are ordered by what they unblock.

1. **Read all five rubric ladders in `config.py`** (remaining-work item 5),
   starting with the eight anchors listed there. They are binding, they are a
   derivation, and they have been audited but not reviewed. Doing this first
   means the paid run scores against a rubric you have actually approved.
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
