# CLAUDE.md

## Read This First

This repository now contains two applications that share one Python package:

1. **Brief Crew** - the original Researcher -> Analyst -> Writer pipeline with a warm Pinecone cache.
2. **Validator Studio** - an additive six-agent startup validator with a FastAPI/WebSocket service and Vue 3 + Vue Flow UI.

Read [`AGENTS.md`](AGENTS.md) before changing CrewAI code. The specifications in [`agents/`](agents/) remain authoritative for behavior they already cover. [`PRD.md`](PRD.md) extends those specifications for Validator Studio.

**Two files hold the durable knowledge. Neither is optional reading, and
neither should ever be restated here.**

> **[`docs/tech-stack.md`](docs/tech-stack.md) — every version, pin and
> toolchain quirk.** Interpreter, packages, models, external API versions, the
> **thirty-six** environment knobs, and the commands that regenerate each
> figure. **Do not restate a version number here** — link, or the two drift
> apart the way the counts below already have, five separate times.
>
> *(This very paragraph was an example of that: it said "twenty" knobs until
> 2026-09-01, and listed four stack-hygiene defects that had all been fixed or
> withdrawn. It now names no figure it does not own.)*

> **[`docs/gotchas-and-insights.md`](docs/gotchas-and-insights.md) — the
> mistakes, and how not to repeat them.** 30 numbered entries, each one
> symptom → cause → what to do, and each one something *not discoverable from
> the code*: the Public Suffix List blocking `.onrender.com` cookies,
> `create_all()` never altering a table that already shipped, `pkill` reporting
> success on Windows while the old process keeps serving, and a whole section
> on **tests that pass for the wrong reason**. The deployment traps 1–8 live
> there now; the numbering is unchanged so existing references still resolve.
>
> **Read it before a deployment, before adding a column, and before believing a
> green suite.**

[`new features/feature-list.md`](new%20features/feature-list.md) was last
reconciled against source and tests on 2026-08-29. **That is four commits and
one uncommitted working session ago**, so treat it as a historical document:
its Complete rows predate the report-truncation defect, the `cost_usd` defect,
the query-shape defect, the two rubric Criticals, the orphaned-run defect and
everything in the current tree. This file is newer. Neither is a substitute for
re-running the suite - the counts move.

**Reconciled 2026-09-01 against HEAD `e910d7d` plus an UNCOMMITTED working
tree** - the Better Auth work (section 13) is not in any commit. The previous
reconciliation said 2026-08-31 at `c63aca0`; that was already a commit behind
when this pass started, which is the usual story here.

**This file was reconciled on 2026-08-31 against a CLEAN working tree at HEAD
`c63aca0`.** The previous reconciliation (2026-08-30) was written against
`d3523c5` plus fourteen modified and seven new files; those changes are now
committed, and **eleven commits** have landed since `d3523c5`. Where a claim
rests on committed history it says so.

## Verified Baseline

Re-measured on 2026-08-31 against **HEAD `c63aca0`, clean tree**, on Windows.
Both suites were run; the two build steps were not.

```text
CrewAI: 1.15.18                 Python: 3.13.5
Python tests:   772 run, 0 failures, 0 errors, 1 skipped - 32.6s
Frontend unit:  324 run, 0 failures, 26 files (Vitest + jsdom) - 6.3s
Frontend build: GREEN - `vue-tsc -b --force` clean over FIVE projects now
                (app, node, vitest, e2e, server), `npm run build` in 464ms
Playwright E2E:   7 tests, ALL GREEN with ZERO console errors tolerated - 14.6s
```

> **Re-measured 2026-09-01 after Better Auth landed.** The 698/311 above it were
> themselves stale: HEAD (`e910d7d`) measured **713 / 324** before a line of
> auth code was written. The 59 added are `test_auth_jwt.py` (28),
> `test_auth_endpoints.py` (25) and `test_additive_migration.py` (6). The
> frontend count did not move - the auth work changed existing specs rather
> than adding files.
>
> **`npm run build` is three steps now**, not two: `vue-tsc -b`, `vite build`,
> then `tsc -p tsconfig.server.json` emitting the Node server to `server-dist/`.

⚠️ These counts move, and they move fast. The Python suite has gone
65 → 295 → 341 → 378 → 415 → 459 → 522 → 537 → 660 → 679 → 698 and the frontend
103 → 116 → 126 → 133 → 165 → 203 → 284 → 311. Re-run before quoting a number;
the command is the contract, not the figure.

> **Both figures above were published wrong until 2026-08-31.** This file
> claimed 537 and 165/16-files; the real numbers were 660 and 203/19-files, a
> 23% undercount on the Python side. README.md, `new features/feature-list.md`
> and `agents/07-deployment.md` were a further generation behind at 415/126.
> Nothing was careless — the tree simply moved eleven commits and the prose did
> not follow. This is the argument for
> [`docs/tech-stack.md`](docs/tech-stack.md) carrying the numbers and everything
> else linking to it.

> **The keyless run was NOT re-measured this pass.** The 660 above was measured
> with `.env` in place. `d3523c5`'s own commit message reports 522 green *with
> and without* `.env`, and nothing in the working tree touches
> `tests/__init__.py` or the import-time key demands - but that is an inference,
> not a measurement, and the mechanism below is exactly the kind that fails
> silently.

> **Why the keyless run matters at all.**
> `src/brief_crew/__init__.py` calls `load_dotenv(..., override=True)` at
> import, and ~40 tests *construct* a real `LLM` or
> `FirecrawlScrapeWebsiteTool` to assert their wiring. Both demand a key in
> `__init__`. Move `.env` aside — which is exactly what a clean checkout and CI
> see — and the suite once did not fail so much as fail to start:
>
> ```text
> Ran 378 tests in 5.738s
> FAILED (failures=4, errors=36, skipped=1)
> ```
>
> The runtime is the tell: **5.7s against ~37s.** Nothing ran, while the README
> claimed `git clone && python -m unittest` "costs nothing and touches no
> network" — true about money, false about running.
>
> `tests/__init__.py` now `setdefault`s two obviously-fake placeholders before
> anything imports `brief_crew`. A placeholder is not a credential — it
> authenticates against nothing — but if you ever add a test asserting
> key-absent behaviour, it must clear the environment itself, the way
> `tests/tools/test_github_feasibility.py` already does with
> `patch.dict(os.environ, {}, clear=True)`.
>
> **Moving `.env` aside is the one hazardous step in this verification**: it
> holds seven live keys. Restore it from a shell trap that fires on any exit,
> name the backup so the ignore rules cover it (`.env.*` does — confirm with
> `git check-ignore -v` on the actual filename, never by reading `.gitignore`;
> see [gotchas](docs/gotchas-and-insights.md) 5 and 27), and check the file is back before you finish. Entry 27
> also carries the trick that shrinks the exposure window from minutes to
> seconds. That hazard is why
> this pass did not repeat it.

Commands used:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .

Push-Location frontend
npm test
npx vue-tsc -b --force
npm run build
Pop-Location
```

And the run that actually proves the no-key claim - in Git Bash, because the
trap is the point:

```bash
restore() { [ -f .env.ci-bak ] && mv -f .env.ci-bak .env; }
trap restore EXIT INT TERM
mv .env .env.ci-bak
./.venv/Scripts/python.exe -m unittest discover -s tests -t .
```

**CI was green on `d3523c5`, and its status on the eleven commits since has NOT
been checked** - this pass made no network call to GitHub. Treat everything in
this paragraph as of `d3523c5`, not as of HEAD. Run `33302040348`,
`ubuntu-latest`, both jobs `success`, 45s. Every push since `2240054` had been
green
(`33295730271`, `33297570325`, `33298411682`, `33299927607`, `33302040348`);
the three before that - `5daf401`, `a3e5268`, `53afa66` - were all `failure`
with byte-identical counts. That green also closes the standing "never verified
on Linux" caveat: the suite runs on a clean Ubuntu checkout with no `.env` and
no credential of any kind. `.github/workflows/ci.yml` carries no `env:`
credentials by design, which is what makes the README's "costs nothing and
touches no network" claim checkable rather than aspirational.

**The tree is now clean, so CI has seen everything measured above — but no CI
run at `c63aca0` was inspected this pass.** The 660/203 figures were measured
locally on Windows. Run `33302040348` measured the committed 522/133 at
`d3523c5`, eleven commits back.

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

> **Add an `__init__.py` in the same commit as any new test directory**, or
> `unittest discover` walks past it in silence and reports a green `OK` over
> tests it never ran. The Python count sat at 65 for a long time because of
> exactly this. Full entry:
> [gotchas](docs/gotchas-and-insights.md) 20.

The test suite is deliberately no-cost: CrewAI crews, external APIs, OpenRouter, Pinecone, Cohere, and Firecrawl are mocked or replaced with deterministic runners where needed.

## Deployment — Live

The app is deployed on Render and serving.

| | |
| --- | --- |
| UI | `https://agentic-crew-ai-web.onrender.com` — static site, free plan |
| API | `https://agentic-crew-ai-api.onrender.com` — web service, python, **starter**, **singapore** |
| DB | `agentic-crew-ai-db` — basic_256mb, PostgreSQL 18, singapore. Pre-existing and **reused**, not recreated by the apply |
| Repo | `https://github.com/simonraj79/multi_agent_crewai_startup_advisor` (**public**), branch `main`, `autoDeploy: yes` on both services |
| Commit | **Inferred `d3523c5`**, not read back — the service exposes no version endpoint. Local `main` and `origin/main` are both `d3523c5`, CI is green on it, and `autoDeploy: yes` is set on both services. Nothing in the current working tree is deployed |

> **Every live measurement below was taken on 2026-08-30 at `e539811` and was
> NOT re-probed this pass.** Four commits have shipped since. Nothing in them
> obviously changes any of these answers, but "obviously" is doing work in that
> sentence — re-probe before quoting one as current.

- `GET /readyz` → `"storage":{"backend":"postgresql"}`.
- `GET /api/workflows/idea-validator/graph` → **14 nodes, 16 edges**. (This one
  *was* re-checked locally this pass: `VALIDATOR_GRAPH` is still 14/16, and
  `BRIEF_GRAPH` is 7/6.)
- Preflight `OPTIONS /api/workflows` → **200** for
  `Origin: https://agentic-crew-ai-web.onrender.com`, **400** for a
  disallowed origin.
- `wss://…/ws?session_id=…&run_id=…` → **HTTP 101** upgrade.
- `GET https://agentic-crew-ai-web.onrender.com/` → 200.
- `GET /healthz` → **200**.
- `GET /docs` and `GET /openapi.json` → **404**. This is also the proof that the
  deployed instance is **not** synthetic: `expose_docs` is
  `EXPOSE_API_DOCS or synthetic`, so a synthetic instance would serve them. The
  deployed service is in paid mode.
- `POST …/runs` with a 70 KiB body → **413**,
  `the request body is limited to 65536 bytes`, refused at the ASGI layer
  before anything parsed it.
- `POST …/runs` with a 2001-character idea → **422**,
  `inputs.idea is limited to 2000 characters; this one is 2001`.

Neither POST launches a run, so both probes are free.

> **Money has been spent on this deployment, and the first paid run happened.**
> `aa7bdc1`'s commit message reports three defects "found by the first
> end-to-end paid run rather than by tests", with measured figures: a report
> truncated at 4096 characters, `cost_usd = 0.0` after **128,069 real tokens**,
> and two of three research branches returning nothing. `add21d1` adds that the
> run scored `NEEDS_WORK 4.2` at **0.17 confidence** with `provisional=false`.
>
> So the earlier reading of `/readyz`'s `"gates":{"open":1,"expired":0}` is
> explained: a real run was launched, and it completed. **Item 1 still does not
> close.** What that run produced was a truncated report priced at zero against
> a rubric with two Critical defects, none of which is a clean acceptance
> result. Citation closure over an acceptance set remains uninspected.

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

**Moved to [`docs/gotchas-and-insights.md`](docs/gotchas-and-insights.md), which
is now the only copy of the *reasoning*.** The numbering is unchanged, so every
existing "see trap 5" still resolves.

[`docs/deploying.md`](docs/deploying.md) legitimately restates two of these as
runbook steps - somebody following a deploy needs to be told about
`ipAllowList` and `VITE_API_URL` at the moment it matters, not sent elsewhere.
That is the one duplication worth keeping, and it is also the one that has
already drifted once: both it and `render.yaml` asserted the live database
"already has an allow list", a control that does not exist, until `e539811`.

The index below is titles only, deliberately. The *reasoning* is the valuable
part of each one and it lives in a single place; restating it here would
recreate the problem this move solves.

| # | Trap |
| ---: | --- |
| 1 | The database's `ipAllowList` is empty |
| 2 | `VITE_API_URL` is a build-time variable, and getting it wrong is silent |
| 3 | Render snapshots a deploy's environment when the deploy is *created* |
| 4 | `vue-tsc -b` is incremental, and it type-checks more than `src/` |
| 5 | `.gitignore` matched `.env` and nothing near it |
| 6 | A line-anchored `grep` under-reports `config.py` |
| 7 | `onrender.com` is on the Public Suffix List |
| 8 | A free Render web service sleeps, and that decides your architecture |

That file carries **30 numbered entries** plus a set of reusable design
insights. It covers the toolchain (`tsc -b` skipping an unreferenced config,
Node's literal import resolution, Vite proxy ordering), the runtime
(`create_all` never altering a shipped table, `value or DEFAULT` eating a
legitimate zero, `Authorization` not being CORS-safelisted), an entire section
on **tests that pass for the wrong reason**, and the process traps - `pkill`
silently failing on Windows, and why the counts in this very file have been
wrong five times.

**Read it before a deployment, before adding a column, and before believing a
green suite.**

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

The implementation uses **six** single-agent Crew wrappers around six agents -
`ScopeCrew`, `MarketCrew`, `SentimentCrew`, `FeasibilityCrew`, `SynthesisCrew`
and `ReportCrew`, one `@CrewBase` each in
`crews/validator_crew/validator_crew.py` (lines 135, 165, 200, 237, 276, 331).
This file said "five" for several handoffs; verify with
`grep -c '^@CrewBase' src/brief_crew/crews/validator_crew/validator_crew.py`,
which answers 6. All prompts and output contracts are YAML-first.

Every one of the six tasks in `crews/validator_crew/config/tasks.yaml` now
carries `guardrail_max_retries: 2` — see **section 11(b)** below for why that is
not a cosmetic default.

### 3. Validator Flow

[`src/brief_crew/validator_flow.py`](src/brief_crew/validator_flow.py) implements:

```text
scope -> scope gate -> three parallel research branches
      -> synthesis -> verdict gate -> report -> output/validation.md
```

Key behavior:

- Structured `ValidatorState`.
- Native CrewAI `@human_feedback` at both gates, with **`llm=None`** — see
  **section 11(a)** below.
- Deterministic routers for approve/revise decisions with no LLM routing call.
- Three sibling synchronous `@listen("scope_approved")` methods, so CrewAI runs branch crews concurrently in worker threads.
- `and_()` fan-in before synthesis.
- Dependency-injected crew factories for no-cost tests.
- `no_gates=True` mode for CI and headless deterministic execution. This is a
  *state field*, not an input the public API accepts — see section 9's gates
  contract and `RESERVED_RUN_INPUT_KEYS`.
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
- `Competitor` — now carrying `free_core_coverage`
  (`WHOLE_JOB` / `MOST_OF_JOB` / `SEPARABLE_PART` / `NONE`, nullable, and
  `None != "NONE"`), the field added in `d3523c5` to repair rubric finding F1
  (`schemas/validator.py:170`).
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

> **One deviation in `d3523c5` a human should still ratify:** `provisional` now
> also covers `INSUFFICIENT_EVIDENCE`. PRD §10.3 flags only a REJECT at
> 0.35-0.60, which makes the flag non-monotonic in the quantity it keys on — a
> REJECT at 0.36 is labelled while the first live run at 0.17 confidence with
> two empty branches was not.

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

The `zero_ok` / `one_ok` bounds moved in `d3523c5` to repair rubric findings F1
and F2 (`validator_guardrails.py:552-608`). Verified at head:

```text
D  zero_ok = usable >= RUBRIC_FLOOR_MIN_USABLE_THREADS and problems == 0
   one_ok  = usable <  RUBRIC_FLOOR_MIN_USABLE_THREADS and problems == 0
M  zero_ok = sources >= 1 and segments == 0
X  zero_ok = live >= 1 or free_whole >= 1
```

D's floor and D=1's lower bound now move together, because the review's own
repair applied literally deadlocks the ladder: with D=1 left as "no usable
thread", the 1-2 thread states satisfy neither predicate and every score 0-5 is
rejected. `tests/validator/test_rubric_critical_fixes.py` (22 tests) asserts the
partition is total over 75 evidence states rather than arguing it in a comment.

### 6. Research Tools

Implemented in [`src/brief_crew/tools/`](src/brief_crew/tools/):

- `market_research.py` - Firecrawl v2 search and scrape; handles both documented result URL shapes.
- `hn_sentiment.py` - HN Algolia story search plus comment-tree retrieval; cites HN item URLs.
- `github_feasibility.py` - GitHub search with required `User-Agent`, optional token, and shared thread-safe rate limiting.

Every tool returns a JSON envelope containing `status`, `tool`, `query`, `retrieved_at`, `result_count`, `results`, and `notes`.

**The two keyword branches now broaden a narrow query rather than reporting an
absent market.** `aa7bdc1` found, against the live tools, that the Scoper's
prose-shaped queries returned nothing:

```text
HN Algolia  "AI tool creates educational materials assessment"  -> 0
            "AI grading teachers"                               -> 5
GitHub      "AI tool that creates educational materials..."     -> 1
            "quiz generator LLM"                                -> 5
```

So D=1 on "0 usable threads" and F=1 on thin repos were findings about a query,
not about an idea. The Scoper now writes 2-4 keywords ordered specific-to-broad;
HN and GitHub retry broader, bounded to three attempts, naming the queries
tried. **The market branch is deliberately left alone** — Firecrawl is semantic
and forgives the same phrasing — and `tests/validator/test_query_shape_prompts.py`
(10 tests) pins that asymmetry so nobody "fixes" it by analogy.

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

**Frames are attributed to the agent that produced them** (`d3523c5`). Tool,
LLM and token frames were all landing on the `unattributed` quarantine node,
because `AgentExecutor` is itself a Flow and CrewAI's
`current_flow_method_name` therefore read `execute_tool_action` — its method,
not ours. A node scope is now carried explicitly. Frames gained `query`,
`tool_status`, `result_count` and `notes`, bounded and degrading rather than
raising on malformed output, so a branch that finds nothing says what it asked.
Consequence worth naming: `_record_usage` bills token frames to `frame.node_id`,
so **per-node cost had been reading zero for every run**.
`tests/events/test_tool_frame_attribution.py` (19 tests),
`tests/events/test_nested_flow_frames.py` (11 tests).

The 3x tool emissions seen in the first paid run are three *real* calls —
`guardrail_max_retries` defaulted to 3 and the prompts ask for several queries.
They are not deduplicated; collapsing them would hide two thirds of a branch's
spend.

**`cost_usd` is no longer 0.0 after real tokens.** The computation existed and
missed, for two independent reasons. CrewAI's `LLM.__new__` strips the provider
prefix for native providers, so `LLMCallCompletedEvent` reported
`z-ai/glm-5.3-flash` while `PRICES` was keyed on
`openrouter/z-ai/glm-5.3-flash`, and `PRICES.get(model, (0.0, 0.0))` turned "no
price on file" into "this call was free". A price index resolves both spellings,
and an unknown model returns `None` — not `0.0` — contributing nothing and
logging one warning naming the model. Fixing that alone would still have shown
`$0.0000`: the client reads `details.usage.cost_usd` and the serializer wrote
`cost_usd` *beside* `usage`. It is now nested as well as kept top-level.
**Every figure is tokens x a local price table** — OpenRouter's own
per-generation cost never reaches the process, so this is an estimate and now
says so. `tests/service/test_run_result_and_cost.py`, 23 tests.

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
- **The run result carries the whole report.** `mark_completed` used to clip the
  final result with the *streaming frame* serializer, whose `max_string` exists
  to bound a 2000-frame ring — so the deliverable of the entire system came back
  cut off mid-link and the full text existed only in `output/validation.md` on
  ephemeral container disk. The body keys named by `RUN_RESULT_BODY_KEYS`
  (`config.py:778`, currently just `markdown_body`) now get
  `MAX_RUN_RESULT_BODY_CHARS` (64 KiB, `config.py:770`) while everything else
  stays frame-clipped. **64 KiB is not a guess**: it is exactly
  `persistence.MAX_STRING_LENGTH`, whose `_sanitize_json` *raises* rather than
  truncates, so a larger in-memory bound would have lost the entire run row at
  write time. Per-key rather than a bigger `SerializerLimits`, because a uniform
  64 KiB across an arbitrary result multiplies by `max_items` and the whole row
  would then fail `_bounded_json`. `RunSnapshot.result`
  (`service/models.py:309`) is what the client reads.

#### The gates contract, and why `inputs` refuses reserved keys

`CreateRunRequest` gained a **declared** field
(`service/models.py:106-118`):

```python
gates: Literal["human", "auto"] = "human"
```

`human` pauses at the scope and verdict gates. `auto` answers them itself and
runs the whole pipeline unattended. `create_run` (`service/app.py:576-597`)
refuses `auto` with **403** unless `VALIDATOR_ALLOW_AUTO_GATES` is set (`config.py:858`), and with
**422** for a workflow that has no gates to skip. 403 rather than 422 is
deliberate: the request is well formed and would be honoured elsewhere, so the
client can tell "I sent this wrong" from "this server will not do that".

**Why the flag defaults off is a cost decision, not a security one.** A gated
run stops after the Scoper — one escalation-tier call — and if nobody replies it
simply expires. *Human inaction is the de facto spend cap*, and that is what made
an unauthenticated Launch button survivable at all. An auto run has no such
brake: Scoper, three branches with live Firecrawl/HN/GitHub calls, Synthesist at
`reasoning_effort=high`, then Reporter, bounded only by the agents' summed
`max_iter`. `RUN_RATE_LIMIT_MAX_RUNS` was calibrated against runs that stop at
the first gate; ten *complete* pipelines per minute per client is a different
order of spend.

**And this is why `inputs` now refuses reserved keys with a 422.** CrewAI merges
kickoff inputs into the flow's pydantic state wholesale
(`{**current_state, **inputs}` then `model_validate`), so **every field on
`ValidatorState` was settable from the public unauthenticated request body** —
`no_gates` among them (`validator_flow.py:151`). That was the `gates` field
wearing a disguise, reachable with no flag, no validation and no record.
`RESERVED_RUN_INPUT_KEYS` (`config.py:867`, currently `no_gates` and
`sequential_branches`) is refused rather than silently dropped: answering 422
tells an honest client its request was misread, where dropping the key would let
a stale one think it had switched modes. The check lives on the model, so it
fires before the handler — which is what makes the 403 above meaningful, since
setting `run_inputs["no_gates"] = True` in `create_run` is then the *only* way
that field can become true. `tests/service/test_gates_mode.py`, **19 tests**,
including both smuggling attempts and an unattended run completing with no gate
reply.

- **Admission control on the one endpoint that spends money.**
  `POST /api/sessions/{id}/runs` is unauthenticated *by design* — the demo is
  meant to be clickable — and until `e539811` it was unbounded in every
  dimension that mattered: a 1 MB body reached the app with no 413 from any
  layer, and `ThreadPoolExecutor`'s internal queue is unbounded, so
  `RUN_CONCURRENCY` bounded parallelism and *nothing* bounded admission. Four
  layers now guard it, five distinct refusals:

  | Condition | Status | Detail |
  | --- | --- | --- |
  | declared `Content-Length` > `MAX_REQUEST_BODY_BYTES` (64 KiB) | **413** | `the request body is limited to 65536 bytes` |
  | client over `RUN_RATE_LIMIT_MAX_RUNS` per `RUN_RATE_LIMIT_WINDOW_SECONDS` (10 / 60 s) | **429** | `too many runs from this client; wait and try again` + computed `Retry-After` |
  | `inputs` JSON > `MAX_RUN_INPUT_BYTES` (8 KiB), > `MAX_RUN_INPUT_KEYS` (16), or carrying a reserved control key | **422** | pydantic `Value error, …` |
  | idea/topic > `MAX_RUN_INPUT_CHARS` (2000) | **422** | `inputs.<name> is limited to 2000 characters; this one is N` |
  | registry at `MAX_QUEUED_RUNS` (8) | **429** | `the service is at capacity; try again shortly` + `Retry-After: 30` |

  The rate limit runs **first** in `create_run`, before the workflow and input
  checks, so a flood of deliberately malformed bodies is throttled too. It is
  the only limited endpoint: `/healthz`, `/readyz` and every read-only `GET` are
  left alone so monitoring and a reconnecting UI are never affected. Two
  carve-outs are deliberate, and a naive cap gets both wrong:

  - **A run WAITING at a gate holds no admission slot.** `_execute` has already
    returned by then and its worker thread is free, so a room full of people
    thinking about a scope costs nobody a launch
    (`registry.py::_active_slots`).
  - **Resumes and gate replies bypass admission entirely.** `RunAdmissionError`
    is raised from exactly one place — `create_run` — and `answer_gate` →
    `_submit` cannot raise it. A flood must never strand a human mid-run.

  `RunAdmissionError` is deliberately distinct from `RunBusyError`, and the
  distinction is the whole point: busy means *this* run is mid-execution and
  resending the reply works (**503**); admission means the server is full
  (**429**).

  **Honest residual: a chunked POST declares no `Content-Length` and slips past
  the 413.** `RequestBodySizeLimitMiddleware` says so in its own docstring. The
  pydantic `inputs` bound and the 2000-character prompt bound behind it still
  cap what reaches a model, so the *cost* is bounded either way — the body is
  not.
- **`/docs`, `/redoc` and `/openapi.json` return 404 unless `EXPOSE_API_DOCS=1`
  or the instance is synthetic.** Obscurity, not a control, and `app.py` says
  so where it does it. Verified 404 against the deployed API at `e539811`.
- CORS middleware driven by `CORS_ALLOW_ORIGINS` in `config.py`:
  comma-separated origins, **empty default, so it fails closed**; a malformed
  entry is refused *at import* with the corrected string in the message rather
  than normalised away; `CORS_ALLOW_CREDENTIALS` is a fixed `False`, which is
  what makes the `"*"` escape hatch survivable. **It does not govern `/ws`** —
  browsers do not apply CORS to a WebSocket handshake and Starlette passes
  non-HTTP scopes straight through. See remaining-work item 13.
  `CORS_EXPOSE_HEADERS` is `("ETag", "Retry-After")`: neither is
  CORS-safelisted, and the static site is a separate origin, so without the
  second entry a rate-limited browser client cannot read the one header that
  tells it when to come back.
- **An interrupted run reaches a terminal state.** A run executing when the
  process restarts used to be orphaned forever (see closed item 32).
  `VALIDATOR_ORPHAN_RUN_RECOVERY` (default on) and
  `VALIDATOR_ORPHAN_RUN_GRACE_SECONDS` (default 900) drive a startup pass and a
  periodic sweep. `tests/service/test_restart_recovery.py`, 22 tests.
- Synthetic service mode for no-cost integration and UI testing, selected by
  `SYNTHETIC=1` through `app_from_env()`.

**Environment knobs: there are THIRTY-SIX, and the canonical list lives in
[`docs/tech-stack.md` §6](docs/tech-stack.md).** Thirty-two are read in
`config.py`, four in `service/app.py` (`DATABASE_URL`, `HOST`, `PORT`,
`SYNTHETIC`). Regenerated 2026-09-01 with the multiline scan below.

> **This count has now been wrong FIVE times, and never twice for the same
> reason.** *Eleven*, when the line-anchored grep of
> [gotchas](docs/gotchas-and-insights.md) 6 hid four wrapped
> calls. Then *fifteen*. Then *eighteen*. Then *twenty* — the figure this file
> carried until 2026-09-01, which was short by **sixteen**. Only four of those
> are the new `AUTH_*` / `VALIDATOR_REQUIRE_AUTH` knobs; the other twelve
> (`VALIDATOR_BRANCH_MAX_ITER`, the four `VALIDATOR_FIRECRAWL_*`,
> `MAX_QUEUED_RUNS`, `RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS`, `EXPOSE_API_DOCS`
> among them) were already there and already undocumented, in a paragraph whose
> own previous correction says *"the regex was fixed; the process was not."*
>
> The process still is not. The scan below was run and its output pasted; that
> is the only method that has ever produced a right answer here. **Do not read
> the list — regenerate it**, and if the number surprises you, the number is
> right and the prose is old.

Everything else in the admission path is a genuine constant with no override —
`MAX_REQUEST_BODY_BYTES` (64 KiB), `MAX_RUN_INPUT_CHARS` (2000),
`MAX_RUN_INPUT_BYTES` (8 KiB), `MAX_RUN_INPUT_KEYS` (16),
`MAX_RUN_RESULT_BODY_CHARS` (64 KiB),
`RUN_ADMISSION_RETRY_AFTER_SECONDS` (30), `RUN_RATE_LIMIT_MAX_CLIENTS` (4096),
`RUN_RATE_LIMIT_KEY_MAX_CHARS` (64), and the `RESERVED_RUN_INPUT_KEYS` set.

The scan that regenerates it — **multiline**, never line-anchored:

```bash
./.venv/Scripts/python.exe -c "import re,pathlib;pat=re.compile(r'(?:os\.getenv|os\.environ\.get|_env_[a-z_]+)\(\s*\"([A-Z_][A-Z0-9_]*)\"',re.S);print(sorted({n for f in ('src/brief_crew/config.py','src/brief_crew/service/app.py') for n in pat.findall(pathlib.Path(f).read_text(encoding='utf-8'))}))"
```

`render.yaml` sets **none** of the admission knobs, so production runs on the
defaults above — including `VALIDATOR_ALLOW_AUTO_GATES` off, which is the right
answer for a public endpoint. One knob needs a decision anywhere else:
`RUN_RATE_LIMIT_TRUST_FORWARDED_FOR` defaults to **on**, which is right behind
Render's proxy — the socket peer *is* the proxy, so without it every visitor on
earth shares one bucket and the first person to click Launch rate-limits
everybody else. Turn it **off** for any deployment reachable directly, where
`X-Forwarded-For` is attacker-supplied and the limiter stops limiting.

Service entry point:

```powershell
.\.venv\Scripts\serve.exe                      # paid runners
$env:SYNTHETIC = "1"; .\.venv\Scripts\serve.exe  # no-cost doubles
```

`serve()` hands uvicorn a factory **by name**, and a string factory cannot
receive kwargs, so for a while the console script could only ever build the
paid runners — anyone starting the service to look at the UI spent real money
the moment they pressed Launch. `app_from_env()` is the indirection that fixes
that. `HOST` and `PORT` are read from the environment (see remaining-work item 8).

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

### 11. Two CrewAI cost optimisations, and what each actually saves

Both are in the current working tree, both are pinned by tests, and they are
recorded together because the *reasoning* is the same shape: CrewAI charges you
for something before it checks whether it will use it.

**a. The gates carry `llm=None`** (`validator_flow.py:416-425` and `527-536`).
`emit=None` means CrewAI never collapses a gate reply to an outcome, so the gate
LLM is unreachable — but `_run_human_feedback_step` deserializes it *before* it
checks `emit`
(`crewai/flow/runtime/__init__.py:3608-3611`, verified at 1.15.18), so naming
`CHEAP_MODEL` there built two `OpenAICompatibleCompletion` clients per run, four
httpx pools and four SSL trust stores, and discarded all of it.
`_validate_human_feedback_options` only requires `llm` when `emit is not None`
(`crewai/flow/human_feedback.py:206-218`), so `None` is legal.
**Measured saving: 0.73s of wall clock per run** — that figure is the change
author's measurement, recorded in the source comment; it was not re-measured
during this reconciliation. `tests/validator/test_flow.py` now asserts
`assertIsNone(scope_gate.llm)` and the same for the verdict gate, so a future
edit cannot quietly reintroduce the cost.

**b. `guardrail_max_retries: 2` on all six tasks**
(`crews/validator_crew/config/tasks.yaml`). **This one is a computed bound, not
a measurement.** Two guardrails run on `reporting_task`, and CrewAI counts
retries *per guardrail* — `_guardrail_retry_counts` is a
`dict[int, int]` keyed by guardrail index
(`crewai/task.py:303-305`) — so the unset default of 3 permitted up to **8 full
report regenerations plus 4 judge calls**, all on the escalation tier, because
CrewAI builds a string guardrail as an `LLMGuardrail` with *the agent's own
llm* (`crewai/task.py:435`). Two attempts is the judgement that if a focused
retry has not fixed a citation, the defect is upstream in the branch findings
rather than in the writing. Nobody has measured the actual saving on a live run.

### 12. Validator Studio Frontend

[`frontend/`](frontend/) is a working Vue 3 + TypeScript + Vite + Vue Flow application, not a landing page.

Implemented UI behavior:

- Fixed live validator topology.
- Five node states: idle, running, waiting, completed, error. The `waiting`
  state is set by `applyGate`, not by the event type — see remaining-work item 12.
- **`running` and `completed` no longer look identical.** They shared
  `--gradient-brand` verbatim, so the only thing separating "this agent is
  working" from "this agent is done" was a state chip that the graph's own
  default fit renders at under 5px. Running is now cyan, completed is mint
  (`WorkflowNode.vue:131-148`).
- Custom animated edges driven by structured events.
- Collapsible activity/chat rail.
- Scope and verdict gate cards with editable fields.
- **A rendered validation report** (`components/ReportPanel.vue`). Until this
  existed the console showed nothing at the end of a run — not the verdict, not
  the score, not the report — while the body was on the wire the whole time. See
  closed item 33 for how that survived a green suite.
- **A crew progress strip** (`components/CrewProgress.vue` +
  `data/crewStages.ts`) — see below. The three rowers are named at the
  fan-out, and the strip now says which **pass** the crew is on.
- **A two-rower crew badge on the running node itself** (`WorkflowNode.vue`),
  and a `×N` lap chip on any node that has run more than once.
- A Review / Unattended gates toggle in `StatusPanel.vue`, disabled while a run
  is active, wired to the `gates` request field.
- Launch, relaunch, cancel, and log-download controls.
- Reconnecting WebSocket client with replay and deduplication.
- Refresh recovery from saved run context and `GET /api/runs/{id}`.
- Run and per-node token/cost display.
- Error and reconnect states.
- A header connection badge that no longer reads "Offline" on a working page.
  `connectionLabel` (`frontend/src/App.vue`) reports the probed transport while
  nothing is streaming and hands back to the socket's own state once a run is in
  flight; `Mock mode` still surfaces. See closed item 31 for the two things it
  deliberately does not do.
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

#### The Markdown renderer is escape-first, and that is the whole design

`src/utils/markdown.ts` (240 lines, 22 tests) is a deliberately small Markdown
subset renderer rather than `marked` + `dompurify`. The body it renders is
written by the Reporter agent — model output, untrusted by construction — and a
sanitiser is a denylist applied *after* markup exists. This is the opposite
order:

1. Every character of input is HTML-escaped **first** (`escapeHtml`).
2. Only then is structure recognised, and every tag emitted is a literal in
   that file.
3. The one place an attacker-influenced value lands inside a tag is a link
   `href`, and `safeHref` admits only `http:` / `https:` (plus inert relatives).

So there is no path by which input text becomes markup. Control characters are
stripped rather than escaped, which is also what makes the code-span `SENTINEL`
unforgeable from input. `markdown.spec.ts` pins that property, not the
prettiness of the output. The supported subset is exactly what `tasks.yaml`
asks the Reporter for; anything else degrades to an escaped paragraph.

The `.markdown-body` rules live in `studio.css`, **global rather than scoped**,
because the body is injected with `v-html` and Vue's scoped-style data attribute
is never applied to any of it — a scoped selector would match nothing.

#### `crewStages.ts` declares the pipeline's order, and asserts its own coverage

The graph descriptor has no ordering: its nodes arrive as an unordered array
with hardcoded coordinates, and the only sequence signal in the UI was an
`eyebrow` string rendered at 11px CSS, which the default fit (scale 0.457)
shrinks to roughly 5px. So the console drew a topology but never answered the
two questions an operator has — how far along is this, and what is working right
now.

`data/crewStages.ts` declares seven ordered stages (`scope`, `gate-scope`,
`research`, `score`, `gate-verdict`, `report`, `brief`) over the 14 graph nodes.
Grouping is **declared, not derived**: "these three nodes are one logical stage"
is a judgement about the pipeline, and a topological sort would happily emit the
three research branches as three separate steps, losing the one thing that makes
them interesting — that they happen at once.

`assertStageCoverage(descriptor)` is the safety net. It mirrors the exact-set
match the service performs between `VALIDATOR_OVERLAY` and the derived topology
(`service/graph.py:77-86`): every descriptor node must be in exactly one stage
or explicitly excluded (`unattributed` is instrumentation, not a stage), no node
may be claimed twice, and no staged node may be absent from the graph. It
**returns** problems rather than throwing, so a test can name them and the
runtime can degrade instead of blanking the canvas. Add a node to the flow
without adding it here and `crewStages.spec.ts` (13 tests) fails, rather than
the boat silently skipping it.

`stageProgress` collapses per-node state into per-stage state with a deliberate
severity order — error beats waiting beats running beats completed — so an
errored node is never hidden by a sibling that is merely running, and a gate
WAITING for a human wins outright.

#### The crew shows WHICH node and WHICH pass, and both were missing

The strip shipped able to answer "how far along is this" and nothing more. Two
gaps, closed 2026-08-31:

**It narrated stages, not nodes.** `CREW_STAGES` collapses 14 graph nodes into 7
ordered stages, which is the right call — the three research branches are one
stage because their concurrency is the interesting fact — but the price was
that the fan-out could say "1 of 3 branches home" and never which one. The
`coreIds` now carry `branchLabels` (`Market` / `Signal` / `Build`), the headline
names the branches still pulling, and the per-branch pips bind to each branch's
own state. They previously lit **left to right by count**, so a fast Feasibility
and a fast Market drew the same picture and the picture was wrong.

**The loop was structurally invisible, and it cannot be recovered from
`nodeStates`.** A node that ran four times and one that ran once are both
`completed` afterwards; the map holds no history. So `useValidatorRun` counts
transitions into an *active* state in `nodeVisits`, and that count is what every
lap indicator reads:

- the strip's stage badge (`×3` under `SCOPE`),
- the headline chip (`sent back for a revision`, then `pass 3`),
- the `×N` chip on the node card, which persists after the run finishes and is
  the only place the topology admits it has cycles,
- the node's aria label (`Confirm scope, Waiting, pass 2`).

Two details that are not obvious and are both pinned by tests:

- **`waiting` counts as a visit, not just `running`.** A gate node never becomes
  `running` — `applyGate` is the only thing that touches it and it sets
  `waiting` — so counting `running` alone reported *no* passes for the one node
  an operator revisits most.
- **A repeated `NODE_START` while already running does not count.** CrewAI
  re-emits it on retries and the stream replays on reconnect, so the naive
  version inflated the lap number on a page refresh: the exact moment an
  operator is most likely to be reading it.

#### Three defects the crew work surfaced that no test could have

All three were found by starting a `SYNTHETIC=1` backend and *looking*, which is
the same method that found the two layout defects below.

1. **The boat bounced backwards on every gate answer, and always had.**
   Answering a gate starts that stage's ROUTER, and a router shares a stage with
   the gate it reads. `stageProgress` ranked any `running` above "all cores
   complete", so the stage flipped `completed -> running -> completed` and the
   boat slid back a column and forward again. Invisible until a row-back
   announcement was added, at which point the very first live run announced a
   revision on a run that never revised. Once the cores are done, only a
   declared `reviseIds` node reopens a stage — the same judgement
   `WorkflowNode.vue` already makes when it draws routers as plumbing rather
   than as a stage.
2. **The row-back announcement keyed on the boat's position, which is a proxy.**
   It now keys on a stage's `lap` climbing past 1, which is the event itself and
   cannot mean anything else. It also retires when the crew moves forward: the
   strip was reading "Review — waiting for you / SENT BACK FOR A REVISION" two
   stages past the revision it described.
3. **The rowers were buried under their own boat.** The hull was painted last,
   so every torso and most of each oar were occluded and the first capture
   showed three disembodied heads over a yellow lens. Paint order is now hull,
   oars, rowers; each oar is drawn twice (a casing in the background colour,
   then the oar) because hull and oars are both `currentColor` and dissolved
   into each other; and each oar pivots about its own oarlock
   (`transform-box: fill-box`) rather than about the whole SVG's centre, which
   is what `transform-origin: center top` had been doing.

The strip is also **in the layout now, not over it**. As
`position: absolute; top: 64px` it sat directly on top of the Scoper card and
the scope gate — the two nodes it exists to narrate. `.graph-workspace` is a
three-row grid (`studio.css`), so the Vue Flow container genuinely shrinks
rather than being overlaid, and the stage lane has a fixed `min-height` so a
`×2` badge appearing mid-run cannot resize the graph underneath it.

#### Two layout defects that made the console unusable, and why they were invisible

Both are in `studio.css`, both are commented at the fix site, and both are the
kind that never appear in a unit test:

- **`.studio-main` had an implicit `auto` grid row.** An `auto` row grows to its
  tallest child, so the rails' inner `flex: 1; overflow: auto` resolved against
  an over-tall parent and never had anything left to clip. Measured symptom:
  three panes overflowing an 848px container to **1894px** — the trace list
  stopped scrolling, Launch and Cancel fell below the fold whenever a gate card
  opened, and Vue Flow's zoom controls were pushed off-screen. The fix is
  `grid-template-rows: minmax(0, 1fr)` **plus** `min-height: 0` on the three
  children: a grid item's automatic minimum size is its content, which
  re-inflates the row unless overridden.
- **`.canvas-heading` had an 18px inset.** The two rail collapse toggles are
  absolutely positioned into that strip from either side (`right: -32px` /
  `left: -32px`) and both outrank it on z-index, so they rendered straight
  through the text: the heading read *"XED VALIDATOR GRAPH / vidence pipeline"*.
  Now 40px.

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

### 13. Authentication - Google OAuth via Better Auth

Added 2026-09-01. Sign-in is Google and nothing else; every endpoint that spends
money or reveals a run now demands a verified identity, and runs are owned.

**`frontend/` stopped being a static site.** Better Auth is a TypeScript library
that needs a Node runtime, and this repo had nowhere to put one - the SPA
shipped from a CDN and the API is Python. `frontend/server/` is now a small Hono
service that serves the built SPA *and* mounts Better Auth at `/api/auth/*`,
declared in `render.yaml` as `runtime: node`, `region: singapore`.

Two constraints forced almost every decision here, and neither is visible in the
code that obeys them:

1. **`onrender.com` is on the Public Suffix List.** A browser refuses to set a
   cookie scoped to `.onrender.com`, so Better Auth's usual
   `crossSubDomainCookies` answer is unavailable and a separate
   `agentic-crew-ai-auth.onrender.com` could never share a session with the SPA.
   Serving both from ONE origin is what makes an ordinary httpOnly cookie work.
2. **`region: singapore` is now mandatory on the web service**, where before
   there was deliberately no region at all. It writes sessions to the database,
   and that database's `ipAllowList` is `[]` - only same-region traffic reaches
   it. Move the service and logins break with no configuration change to blame.

**The API is still a separate origin and still cannot read that cookie.** The
SPA fetches a **15-minute JWT** from its own origin (`/api/auth/token`,
authenticated by the cookie) and sends it to FastAPI as a bearer token.
`src/brief_crew/service/auth.py` verifies it offline against
`${AUTH_BASE_URL}/api/auth/jwks`: no shared secret, no database round trip on
the hot path, and an auth service asleep on its Render plan cannot take the API
down with it. The token lives in a module variable in `authClient.ts` and is
**never** written to `localStorage` - the durable credential stays in the
cookie, and the thing exposed to script expires in fifteen minutes.

| Piece | Where |
| --- | --- |
| Better Auth server, Google provider, JWT plugin | `frontend/server/auth.ts` |
| Hono: SPA + `/api/auth/*`, no `/api` proxy | `frontend/server/index.ts` |
| In-process schema migration at startup | `frontend/server/migrate.ts` |
| Token cache, session-gated, in memory only | `frontend/src/services/authClient.ts` |
| The three-phase gate + `unconfigured` | `frontend/src/composables/useAuthGate.ts` |
| Sign-in wall | `frontend/src/components/SignInPanel.vue` |
| JWKS cache and JWT verification | `src/brief_crew/service/auth.py` |
| Setup recipe and every exact string | [`docs/google-oauth.md`](docs/google-oauth.md) |

Things that will bite whoever touches this next:

- **`VALIDATOR_REQUIRE_AUTH` defaults to `bool(AUTH_BASE_URL)`, not to `False`.**
  A flat default fails OPEN: a deployment that sets `AUTH_BASE_URL`, wires the
  login screen and forgets one boolean would serve every paid endpoint
  anonymously with nothing on screen to say so. Configuring an auth server *is*
  turning auth on, so the half-configured state does not exist. Startup also
  refuses `VALIDATOR_REQUIRE_AUTH` with no `AUTH_BASE_URL`, and refuses `"*"`
  CORS while auth is required - the rule `config.py` already wrote for itself.
- **`Authorization` had to be added to `CORS_ALLOW_HEADERS`.** It is not
  CORS-safelisted, so without it the browser preflights, drops the real request,
  and the failure reads like the API being down. It does **not** flip
  `CORS_ALLOW_CREDENTIALS`: that governs cookies, which never cross this origin.
- **Another user's run answers 404, not 403.** A 403 confirms the run exists. A
  run with **no** `user_id` stays readable by anyone, because rows written
  before auth existed cannot be given an owner and refusing them would make
  deploying this destroy the history it organises.
- **The `/ws` credential is a query parameter**, because the browser WebSocket
  API cannot set headers on a handshake. A URL is logged where a header is not;
  what bounds it is that this is the 15-minute JWT, never the session.
- **`user_id` was added to a table that already shipped.** `create_all()` is
  create-if-absent *per table* and does nothing to an existing one, so the
  column would have been silently missing on every deployed database and failed
  at the first INSERT. `persistence._add_missing_columns()` is the idempotent
  additive-only migration; anything needing a backfill or a NOT NULL is the
  point at which a real migration tool has become cheaper.
- **The Vite proxy order is load-bearing.** `/api/auth` must be declared before
  `/api`, or every Better Auth request is proxied to FastAPI and 404s.
- **`getAccessToken` refuses to fetch until a session is known to exist.** It
  defaults to "no session", and `useAuthGate` flips it. Without that it fired
  `/api/auth/token` on every page load - including in the unit suite, where a
  mocked `fetch` handed the token request the response the test had queued for
  the API call and 25 assertions went off by one.

**Proved against the real thing, not against a stub.** Better Auth's live JWKS
was parsed by the Python verifier into a genuine `Ed25519PublicKey`, and a token
Better Auth actually minted was verified by `verify_token`, with a tampered
signature and a wrong audience both refused. `test_auth_jwt.py` signs real
Ed25519 tokens and pins the forgeries - `alg: none`, and the HMAC
algorithm-confusion attack using the public key as the shared secret, assembled
by hand because PyJWT refuses to *sign* that shape.

> **NOT verified: an actual Google sign-in.** No OAuth client exists yet - the
> Chrome extension was not connected during this session, so the credentials in
> `docs/google-oauth.md` have never been created. Everything up to and including
> "Better Auth mints a token and Python accepts it" is measured; the Google
> redirect itself is not.

#### The E2E suite was broken at HEAD, and not by this work

All five `@launch` tests failed before a line of auth code was written, and the
cause is worth recording because it will recur. `useValidatorRun` defaults
`gatesMode` to **`'auto'`**. Against a backend with `VALIDATOR_ALLOW_AUTO_GATES`
set - which the local `.env` does - the run completes unattended and no gate card
ever appears; against one without it, `create_run` answers **403** and no run
starts. Neither is a bug in the console, but both make a test whose whole subject
is the journey *through* the gates depend on an environment variable it never
mentions. `launchRun` in `e2e/studio.spec.ts` now clicks **Review** and asserts
`aria-pressed`. Verified by running the suite at HEAD with the work stashed:
same failure, no auth involved.

`e2e/vite.e2e.config.ts` also gained a **stub of the auth origin** returning a
signed-in session. A build flag disabling auth was the obvious alternative and is
worse: it would exercise the `unconfigured` phase, which production never
reaches, and leave the header chip, the history panel and the bearer path
untested. The middleware must be registered with `server.middlewares.use`
directly - returning a function from `configureServer` installs it *after* the
`/api` proxy, and every auth path would go to FastAPI and 404.

## No-Cost Integration Coverage

Tests cover:

- Schemas, confidence, floors, and verdict reproducibility.
- Guardrail parsing and URL closure.
- Tool envelope handling and rate limits using mocks.
- Validator cache policy and source-only indexing.
- Three-way Flow fan-out with concurrent test doubles.
- OpenRouter model assignment and no fallback.
- Native CrewAI pause/resume through both gates, and the gates' `llm=None`.
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

Re-counted by running each module alone on **2026-08-31**. Two rows had gone
stale since the 2026-08-30 pass that introduced this table — `test_gates_mode.py`
(15 → 19) and `markdown.spec.ts` (19 → 22) — which is worth knowing about a
table whose whole premise is that it was freshly re-run. The other ten were
exact.

| Module | Tests | What it pins |
| --- | ---: | --- |
| `tests/service/test_additive_migration.py` | **6** | `init_db` against a table that already SHIPPED: the column and its index are added, the pre-auth row survives with a NULL owner, and a second call is a no-op |
| `tests/service/test_auth_jwt.py` | **28** | the verifier against REAL Ed25519 signatures: `alg: none`, the HMAC algorithm-confusion forgery, wrong issuer/audience, JWKS rotation, and a failed refresh that keeps serving the old keys |
| `tests/service/test_auth_endpoints.py` | **25** | who is refused, 404-not-403 for another user's run, the per-user rate-limit key (with a control proving the limit bites), and the unowned-run carve-out |
| `tests/service/test_run_admission.py` | 37 | all five refusals and both carve-outs, plus the chunked request that evades the 413 and the `/docs` gating |
| `tests/service/test_gates_mode.py` | **19** | the `gates` contract, both reserved-key smuggling attempts, the 403 and 422, and an unattended run completing with no gate reply |
| `tests/service/test_run_result_and_cost.py` | **23** | the un-truncated report body and the two independent `cost_usd` bugs |
| `tests/service/test_restart_recovery.py` | **22** | the orphaned-run sweep, the resumable shape adopted back to WAITING, and `cancelling` reaching CANCELLED |
| `tests/service/test_cors.py` | 16 | origin parsing, the fail-closed empty default, the startup refusal, and that `/ws` is **not** covered |
| `tests/service/test_gate_resume_race.py` | 11 | the settling window, the `reopen_gate` rollback and the 503 |
| `tests/service/test_serve_env.py` | 5 | `SYNTHETIC=1` really does select the no-cost runners |
| `tests/validator/test_rubric_critical_fixes.py` | **22** | F1 and F2, with the D partition proven total over 75 evidence states |
| `tests/validator/test_query_shape_prompts.py` | **10** | keyword branches broaden; the market branch deliberately does not |
| `tests/events/test_tool_frame_attribution.py` | **19** | tool/llm/token frames reach the right node, not `unattributed` |
| `tests/events/test_nested_flow_frames.py` | **11** | nested-flow frames |
| `tests/events/test_run_state_status.py` | 5 | the `RUN_STATE` frame shape, against a committed fixture |
| `tests/integration/test_ws_gate_replies.py` | 10 | gate replies over the socket |
| `tests/test_brief_crew_regression.py` | 23 | the Track A/B behaviour the platform rules forbid regressing |
| `tests/service/test_graph_etag.py` | **19** | the conditional GET: 304 on the server's own tag, RFC 9110 weak comparison, and that one workflow's tag never satisfies the other's |
| `tests/service/test_synthetic_revise.py` | **19** | the double branching on `decision`: both revise loops, the per-gate turn cap, and that an unknown decision goes forward rather than wedging a run |
| `tests/perf/` | 58 | the fan-out benchmark harness itself — **not** the measurement (item 2) |

Frontend — **all 25 spec files**, from `vitest run --reporter=json` on
2026-08-31 (third pass, after the crew work and the cheap-cleanup sweep). An
earlier version of this table listed six of them, which made a partial view look
like an inventory:

| Spec | Tests | | Spec | Tests |
| --- | ---: | --- | --- | ---: |
| `crewLoop.spec.ts` | **26** | | `downloadLogs.spec.ts` | 10 |
| `crewProgress.spec.ts` | **26** | | `runRecovery.spec.ts` | 10 |
| `markdown.spec.ts` | 22 | | `edgeAnimation.spec.ts` | 8 |
| `mockGraph.spec.ts` | 18 | | `gateCard.spec.ts` | 8 |
| `verdictFrame.spec.ts` | 18 | | `quarantineNode.spec.ts` | 8 |
| `nodeCrew.spec.ts` | **17** | | `routerNode.spec.ts` | 8 |
| `studioApi.spec.ts` | 17 | | `nestedFlowRunState.spec.ts` | 7 |
| `crewStages.spec.ts` | 13 | | `realFrameShape.spec.ts` | 6 |
| `frameHandling.spec.ts` | 13 | | `realVerdictFrameShape.spec.ts` | 6 |
| `gateDerived.spec.ts` | 13 | | `gateNodeWaiting.spec.ts` | 4 |
| `nodeVisits.spec.ts` | 12 | | `mockRun.spec.ts` | 3 |
| `reportVisibility.spec.ts` | 11 | | | |
| `serverLimits.spec.ts` | **19** | | `ideaRecovery.spec.ts` | **8** |
| | | | **Total** | **311** |

The `RUN_STATE` frame shape is pinned on **both** sides against one committed
fixture generated by the real serializer, so backend and client cannot drift
apart again: `tests/events/test_run_state_status.py`,
`frontend/tests/fixtures/backendRunStateFrames.json`, and
`frontend/tests/realFrameShape.spec.ts`.

### End-to-end, in a real browser

`frontend/e2e/studio.spec.ts` (7 tests, Playwright + Chromium) drives the app
against its own `SYNTHETIC=1` backend over a **real** WebSocket: the fixed
topology, live-versus-mock transport detection, the full operator journey
through both durable gates to completion, the waiting gate node, the verdict
gate's read-only fields, a `revise` reply at the scope gate, and run recovery
across a page reload.

**All 7 were run and are green on 2026-08-31**, against a local
`SYNTHETIC=1 PORT=8099` backend. It is no-cost — but it is a *synthetic*
backend, so it proves the plumbing, not the agents.

The double now models `revise` (closed item 15), `no_gates`, and returns a real
`ValidationReport`-shaped result. All three were added for the same reason: a
double that diverges from its subject certifies nothing (see closed items 15
and 33). The revise test consequently asserts the loop — the run returns to
`Confirm scope`, `Revise scope` completes, and the console shows the lap —
where it previously could only assert that the reply was accepted.

> **Killing this backend needs `Stop-Process -Name serve -Force`, not `pkill`**,
> and you must read the serve log rather than trusting a 200 - a stale process
> keeps answering `/healthz` from old code. This has cost time twice now,
> most recently during the authentication work, where it presented as a
> mysterious 401. Full entry, and why `-Name node` is worse:
> [gotchas](docs/gotchas-and-insights.md) 25 and 26.

## Remaining Work and Unverified Risks

Updated 2026-08-31 against `c63aca0`, clean tree.
Numbering is continuous with previous handoffs and has not been compacted, so
cross-references keep resolving.

### Needs money or a live host - no agent can close these

1. **Paid live acceptance run. One paid run has happened; the item does not
   close.** `aa7bdc1` and `add21d1` establish that a real end-to-end run was
   executed against real OpenRouter, Firecrawl, HN and GitHub, and that it
   found three defects no test had. But that run produced a **report truncated
   at 4096 characters**, priced at **$0.00 over 128,069 tokens**, with **two of
   three research branches empty because of query shape**, scored
   `NEEDS_WORK 4.2` at **0.17 confidence** against a rubric whose two Critical
   findings were still open at the time. All three defects are now fixed, and
   none of them has been re-exercised against the live tools. Zero-fabricated-
   citation closure over an acceptance set is still unverified.

   **The standing recommendation against a *scoring* acceptance run is now
   partly lifted.** `docs/rubric-review.md` said *"do not spend money on a live
   acceptance run against this rubric as it stands"* over 13 findings, 2
   Critical and 3 High. Both Criticals were repaired in `d3523c5` and are
   verified fixed at head (section 5). **F4 and the ten others are untouched** —
   `_relevance` still assigns `SOLVES_ENTIRELY` on 75% query-word overlap
   (`tools/github_feasibility.py:244-256`) and `_classify` still assigns `PAYS`
   on a substring hit (`tools/hn_sentiment.py:157-166`). The review document
   itself was **not** updated to record the two repairs; read it alongside
   section 5 rather than instead of it.
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
3. **Live PostgreSQL 18 exercise — still half closed.** `metadata.create_all()`
   has run clean against PG 18 in production: the deployed API answered
   `/readyz` with `"backend":"postgresql"`. Every test still runs on SQLite, so
   that is one DDL pass on one dialect, not coverage.

   **Still open, and one instance cannot close it:** the concurrency.
   `pending_feedback`, the gate reply, the `reopen_gate()` rollback **and now
   the orphan-run sweep** all use `UPDATE ... WHERE ...` + `rowcount`
   compare-and-set. SQLite's single-writer model cannot stress any of them.
   Test two processes replying to one gate.
4. **Firecrawl plan economics (Q3)** and the **Reporter/Scoper A/B tests (Q4).**

### Decisions for a human, not work to schedule

5. **The rubric anchors have been audited, adversarially reviewed, half
   repaired — and still read by no human.** The service is deployed and standing
   by to score a real idea against a rubric nobody has approved.

   What changed: `docs/rubric-review.md` (an *independent agent's* pass, which
   is not what this item asks for) raised 13 findings. `d3523c5` repaired the
   two Criticals:

   - **F1 (Critical, X) — FIXED.** `FLOOR_ALREADY_FREE` counted only GitHub
     repositories marked `SOLVES_ENTIRELY`, so a free *product* that already
     does the whole job could not reach X=0 and scored composite 9.4,
     confidence 0.90, `VALIDATE`, zero guardrail complaints — for the one kill
     PRD §10.2 calls "the most valuable output this system produces".
     `Competitor.free_core_coverage` now exists, the X ladder's anchors and
     ceilings read it, and the two measured scenarios return `NEEDS_WORK` and
     `REJECT / FLOOR_ALREADY_FREE`.
   - **F2 (Critical, D) — FIXED.** `zero_ok = usable >= 1 and problems == 0`
     let one off-hand `OPINION` thread fire `FLOOR_NO_DEMAND` as a **final,
     non-provisional** `REJECT — no demand` at confidence 0.60. The review's own
     repair applied literally deadlocks the ladder, so the floor and D=1's
     lower bound moved together and orphan states fall to level 1.
   - **F4 (High, F and X) — FIXED 2026-08-30.** Three of the four floors and
     the entire VALIDATE gate turned on labels the *tools* pre-computed by
     substring match, shipped under the schema's own field names, so copying
     them was the cheapest valid output a cheap-tier branch agent could produce.
     The tools now report evidence and no verdict: `query_term_overlap` and
     `signal_terms_matched` / `query_terms_present` replace `relevance` and
     `classification`, `_relevance` and `_classify` are deleted rather than
     renamed, and matching is word-anchored so `Payload` no longer matches
     `pay`. Because `Repo` and `Thread` set `extra="forbid"`, an envelope row
     pasted into the schema is now **rejected outright** — copying fails
     validation rather than merely scoring badly. The reviewer's sharpest
     example is also gone: the same repository used to change relevance label
     with the number of words in the Scoper's query, and the reported overlap is
     now identical either way. Pinned by
     `tests/validator/test_rubric_f4_tool_labels.py` (12 tests), including at
     the envelope level.
   - **F3, F5-F13 — untouched.**

   The review is emphatic that the *machinery* held under attack — the level-1
   reservation, the ceiling bounds, anchor separation, the recomputed counts,
   the ordering of the confidence override.

   PRD §10.2 writes out only the **Demand** ladder and labels it
   *"Illustrative"*; M/C/F/X never existed anywhere in the repo and were derived
   from the PRD's stated rules, weights, floors and dimension questions. An
   audit on 2026-08-29 found six unsound anchors (including three in the PRD's
   own Demand ladder) and rewrote all five ladders. They are covered by tests,
   **binding** at 0.85 token overlap in `anchor_problems`, bounded against the
   counted evidence by `score_support_problems`, and quoted verbatim into
   `tasks.yaml`. What is *not* true is that anyone has read them. Audited is not
   reviewed: a derivation error is a judgement nobody made, and it cannot be
   found by running the suite.

   **Read `RUBRIC_ANCHORS` in `config.py` before the next paid run.** These are
   what the audit itself remained unsure of, in the order a reviewer should take
   them. Items 1-6 and 8 are as previously recorded; item 7 has moved twice and
   should be checked against the file, not against this list:

   1. **F=0** — *"repositories returned, none marked SOLVES_ENTIRELY or
      PARTIAL"*. It over-fires for a v1 whose stack is so ordinary nobody
      publishes it, and it triggers `FLOOR_NOT_BUILDABLE`. Over-firing was
      chosen deliberately: the alternative wording rested on no schema field at
      all, and an unreachable floor is worse than a cautious one.
   2. **C=0 vs C=2 splits on `vendor_owned`.** The *definition* of vendor-owned
      written into `market_task` is the auditor's, not the spec's. (Review
      finding F13 argues the flag does the opposite of what `config.py` claims.)
   3. **X=3/4/5's "covers most of the core job" vs "a separable part"** — a
      bounded judgement, not a count, and the hinge the whole X ladder turns on.
      `rubric_support` drops it rather than enforcing it. F1's repair added
      `free_core_coverage` alongside it, so this judgement is now *shared*
      between a schema field and a prose clause.
   4. **D=1 drops the PRD's "<3 usable threads"** — an amendment to the only
      ladder the PRD ever wrote.
   5. **D=2's 24-month boundary replaces the PRD's 36 months**, to close the
      dead band the PRD ladder left between D=2 and D=3.
   6. **M=0 is read as "no nameable buyer"**, dropping the PRD floor's "no
      money" conjunct. Note this one has also moved: `zero_ok` for M is now
      `sources >= 1 and segments == 0`, not `sources >= 1`.
   7. **D=0 vs D=1** — moved again in `d3523c5`. Both are now mechanical
      against `RUBRIC_FLOOR_MIN_USABLE_THREADS`, and the **classification
      itself** is still the Sentiment Analyst's judgement, so the REJECT floor
      rests on labelling rather than on arithmetic — and F4 says that labelling
      is pre-computed by a substring match in the tool. Verify against
      `validator_guardrails.py:552-557`.
   8. **F=5's "together cover the separable parts of the scoped v1"** —
      inherited from the derivation, still judgement, still unenforced.
6. **Sprites (F34).** The PRD's 144 downscaled character PNGs are not in the
   repo, so this cannot be implemented as specified. The frontend ships a
   vector/icon identity instead: no per-agent palette, no hash-based
   assignment, no walk cycle. The new `CrewProgress.vue` strip is the closest
   thing that now exists and is explicitly **not** the sprite system — it is an
   SVG boat with three oars, driven by stage state. Either amend the criterion
   or supply the assets.
7. **Dead scaffold — a seven-file cluster, not five.** Re-verified 2026-08-30,
   all still present, all still unreferenced by anything the app loads:

   - `frontend/src/components/HelloWorld.vue` — imported by nothing.
   - `frontend/src/style.css` — imported by nothing. `main.ts` imports
     `./studio.css`, which is a different file; that is why this one looks used
     to a careless grep.
   - `frontend/src/assets/hero.png`, `vite.svg`, `vue.svg` — `HelloWorld.vue`
     is the **only** importer of all three.
   - `frontend/public/icons.svg` — referenced only by `HelloWorld.vue`'s six
     `<use href="/icons.svg#…">` elements.
   - `frontend/public/favicon.svg` — referenced by **nothing**, and
     `frontend/index.html` has no `<link rel="icon">` at all, so every page load
     requests `/favicon.ico` and 404s. One line of `index.html` fixes that
     independently of whether the rest is deleted.

   **The favicon half is FIXED (2026-08-31).** `index.html` now carries
   `<link rel="icon" type="image/svg+xml" href="/favicon.svg" />`, so the
   `/favicon.ico` request on every page load is gone. That 404 was the only
   thing `e2e/studio.spec.ts`'s `ALLOWED_CONSOLE_ERROR` exemption existed to
   forgive, and the exemption is retired: all seven E2E tests now pass with
   **zero** console errors tolerated, which is how the fix was verified rather
   than assumed. The other seven files are still dead and still need a
   keep-or-delete decision.

   Plus an eighth artefact: `.gitignore` carries an explicit exception
   (`!frontend/src/assets/**/*.png`, with a comment naming `HelloWorld.vue`)
   added purely to keep `hero.png` alive against the global `*.png` rule.
   Delete the cluster together and drop the exception, or keep all of it — but
   wire up the favicon either way.

### Known gaps with a clear fix

8. **`serve()` binds `127.0.0.1`.** Still true, and still correct for local
   use, but it means the registered console script cannot be a container entry
   point without `HOST=0.0.0.0`. `service/app.py` reads
   `os.getenv("HOST", "127.0.0.1")` and `os.getenv("PORT", "8000")`, so both
   are environment-configurable, and `SYNTHETIC=1` now selects the no-cost
   runners through `app_from_env()` (closed item 22). `render.yaml` still sidesteps
   the binding with an explicit uvicorn command rather than using the script.
9. **An intermittent `RecursionError` in CrewAI's `Flow.resume()`** was seen
   once in ~6 gate-probe runs and never reproduced in a 10-round stress loop.
   It is in `crewai`, not this repo. Resume is what the whole Scenario C
   recovery story rests on, so watch for it before production gate work.
   *Unverified in this pass — reproducing it needs live gate probes.*
10. ~~**The header says "Offline" whenever no run is in flight.**~~ **Fixed in
    `e539811`; the full entry is item 31 in the closed ledger.** The number is
    kept as a stub rather than renumbered, because six other entries and the
    Next Sequence reference items 11-17 by number.
11. ~~**The idea textarea resets after a reload, and nothing bounds it.**~~
    **BOTH HALVES FIXED 2026-08-31.**

    *The bound.* `maxlength` is on the textarea, sourced from
    `data/serverLimits.ts`, where `MAX_IDEA_CHARS` restates
    `MAX_RUN_INPUT_CHARS` with a comment naming its source and a test asserting
    the two agree — duplicated constants drift, so the drift is now a
    failing test rather than a surprising 422. The counter states the ceiling
    (`40 / 2000 characters`), warns in amber inside the last 100 (because
    `maxlength` then starts discarding keystrokes with no feedback at all), and
    explains the disabled Launch below the 12-character minimum, which was
    previously a dead button with no stated reason.

    *The message.* `studioApi.fetchJson` threw
    `new Error(await response.text())`, so a 2001-character idea reached the
    operator as the literal string `{"detail":"inputs.idea is limited to 2000
    characters; this one is 2001"}` — braces, quotes, key and all. The
    server's sentence was already good; the client was showing the envelope
    around it. `readErrorDetail` unwraps both FastAPI shapes (a `detail` string
    and pydantic's list-of-`msg`) and falls back to the raw body rather than
    swallowing anything. A 429 now also reads `Retry-After`, which
    `CORS_EXPOSE_HEADERS` had been exposing cross-origin for a reader that did
    not exist.

    *The reset.* `idea` was a plain ref seeded with a hardcoded default and
    assigned nowhere, so a refresh mid-run restored the graph, the gates and the
    report correctly above a box that had silently reverted to *"An AI tool that
    turns Figma files into production React"* — and the operator's next
    Relaunch would have spent money on something they never typed. `recoverIdea`
    reads it off the run's own opening `RUN_STATE` frame, which `restoreRun`
    already replays: no new persistence, no new API field, and the box shows
    what the run is actually about.

    `tests/serverLimits.spec.ts` (19 tests) and `tests/ideaRecovery.spec.ts`
    (8 tests).

12. ~~**`applyNodeState` has three dead branches against the real backend.**~~
    **ALREADY FIXED before this pass; the entry was stale.** Verified at head:
    `useValidatorRun.ts` dispatches on `START`, `END` and
    `frame.level === 'ERROR'` only, and the comment above it explains exactly
    why the `WAITING` / `COMPLETED` / `ERROR` `event_type` branches were
    removed. No code change was needed on 2026-08-31 — only this
    correction. Its own small lesson: a remaining-work list decays like any
    other prose, and "re-verified open" is only as good as the date beside it.

13. **`/ws` has no `Origin` check.** `CORS_ALLOW_ORIGINS` does not reach it:
    browsers do not apply CORS to a WebSocket handshake and Starlette passes
    non-HTTP scopes through. The socket does require a `run_id` that exists and
    a matching `session_id`, so an attacker needs a run identifier to get
    anything, but nothing stops a page on any origin from opening the socket.
14. ~~**The graph `ETag` is set and never honoured.**~~ **FIXED 2026-08-31.**
    `get_graph` now takes an `If-None-Match` header and answers **304** with an
    empty body and the tag repeated (RFC 9110 requires the repeat, so a cache
    can refresh its own freshness record from the response).

    Measured against the live synthetic service, not assumed: the exact tag
    gives 304 and 0 bytes, `W/"..."` gives 304, and a stale tag gives 200 with
    **10,357 bytes**. That last number is what this endpoint had been sending on
    every page load, for a topology that is constant for the life of a deploy
    and whose `version` the client already stores.

    `_etag_matches` implements RFC 9110 §13.1.2 **weak** comparison. Three
    things it must get right are each a silent-failure mode: the header is a
    comma-separated *list*; comparison is weak even for strong tags, so a proxy
    that weakened the tag in transit must still match; and `*` matches any
    representation. A malformed header degrades to a normal 200, never an error
    — a bad cache header must not fail a request.
    `tests/service/test_graph_etag.py`, **19 tests**, including that one
    workflow's tag never satisfies the other's.

15. ~~**`SyntheticValidatorRunner` does not model `revise`.**~~ **FIXED
    2026-08-31.** `resume()` now reads `decision` and branches:
    `route_scope` —> `revise_scope` —> `confirm_scope` reopens the same gate,
    and `route_verdict` —> `revise_verdict` —> `review_verdict` rescores and
    reopens its own. Bounded at `SYNTHETIC_MAX_REVISE_TURNS = 3` per gate,
    mirroring `claim_revise_turn`: at the cap a further revise goes forward
    rather than parking the run at a gate with nothing left to do.
    `tests/service/test_synthetic_revise.py`, **19 tests**.

    The reopened scope gate carries the **revised** scope — the operator's
    edits laid over the defaults, plus a `revision_note`. Echoing the raw reply
    was tried first and is wrong: the scope gate is fully editable, so every key
    of the gate's output reaches the console as an *input*, and the operator
    would get a text box full of reply JSON.

    **Why this had to be fixed before any of the crew-animation work could be
    trusted:** a console that draws a revision cannot be verified against a
    double with no revisions in it. Both revise edges were dead on the free
    path, so no unit test, no E2E test and no local synthetic run had ever
    traversed one. Fixing it also broke a test that had been asserting the
    *bug* — `test_gate_fields.py::test_the_note_and_a_scope_edit_are_accepted`
    read the echoed reply off the verdict gate that a revise wrongly reached
    — and that test now asserts the corrected contract.

    Original entry, for the record: `resume()` branched on
    `context.metadata["synthetic_stage"]` alone and never read `decision`, so a
    `revise` at the scope gate advanced exactly as `approve` would.
    `resume()` (`service/runner.py:228-260`) branches on
    `context.metadata["synthetic_stage"]` only and never reads `decision` from
    the parsed payload, so a `revise` at the scope gate advances to the verdict
    gate exactly as `approve` would. The revise loop is therefore **never**
    exercised end to end by anything. The `@launch` test named "accepts a Revise
    reply at the scope gate and keeps the run going" is honestly titled: it
    proves the reply is accepted, not that anything loops back. **This now
    matters more than it did** — see item 34, where the in-process revise path
    is suspected of being broken in CrewAI itself, and this double is the reason
    no test would notice.
16. **`render.yaml` hardcodes a value that cannot be known when it is
    written.** `CORS_ALLOW_ORIGINS` is committed as
    `https://agentic-crew-ai-web.onrender.com` — a URL that only exists *after*
    the static site is created, so a first apply into a differently-named
    service ships a wrong value that fails closed and looks like missing
    middleware. **Still open**, and the file still carries the literal.

    The second half of this item is **closed**: `render.yaml:29-41` and
    `docs/deploying.md:90` no longer claim the live database "already has an
    allow list". See [gotchas](docs/gotchas-and-insights.md) 1.
17. **`docs/` is published; the licence is not settled.** All four files
    (`licensing.md`, `deploying.md`, `preflight.md`, `rubric-review.md`) went
    public in `add21d1` and are tracked at head. What was corrected around them:

    - **The third-party teaching material is removed, not reduced.** `d3523c5`
      removed 233 references across 16 files. `agents/workflow.md` and
      `agents/patterns.md` were restructured around Anthropic's *Building
      Effective Agents* vocabulary, which they now cite directly; the sixth
      pattern (⑤ nested teams) has no Anthropic entry and is declared as this
      repo's own in `patterns.md` §6 — CrewAI spells pattern 4
      `Process.hierarchical`, and without a separate name for the nested case
      that collision cannot be discussed. The CrewAI 1.15.18 analysis, every
      file:line finding and every measured number were **kept** — that was
      always original work. 86 cross-file and 170 intra-file section references
      were verified to resolve. ⚠️ Git history still contains the removed text
      (public in `add21d1` and earlier); no history rewrite was done.
    - **`preflight.md` no longer publishes account state.** Balances, the
      OpenRouter `limit: null`, and the Pinecone vector count are gone; each is
      now the *check* to run rather than the answer.

    **Still open: there is no `LICENSE` file at the repo root** (verified
    2026-08-30 — `ls LICENSE*` finds nothing), which for a public repo means all
    rights reserved. `pyproject.toml:6-10` now names Simon Raj as author and
    carries an explicit NOTE that the `license` field is absent and why; that
    is a comment, not a licence. **PRD §8** still reverse-engineers a
    third-party frontend with a Lift/Adapt/Drop plan against a licence nobody
    has recorded.

#### New in this pass

Items 36-39 come from the **2026-08-31 five-agent stack audit**; the full
inventory and the regeneration commands are in
[`docs/tech-stack.md`](docs/tech-stack.md). What unites them: **every one is
invisible to a green test run.** The suite passes at 660, CI passed at
`d3523c5`, the deploy serves. Each is a case where something holds *by accident*
— a transitive pin, a platform default, an unreferenced tsconfig, a comment
nobody diffed against its own value — rather than by declaration. That is the
signature of stack-hygiene debt, and it is why a version audit cannot be done by
running tests.

36. ~~**[High] `pydantic` and `PyYAML` are direct imports that
    `pyproject.toml` does not declare.**~~ **FIXED 2026-08-31.**
    `pydantic>=2.12,<3` and `pyyaml>=6` are now in `dependencies`, each with a
    comment naming where it is imported and why it was missed. Installed
    versions satisfy both (pydantic 2.12.5, PyYAML 6.0.3).

    The reason it was invisible is worth keeping: `pyproject.toml` already
    carried *"Must be named explicitly - crewai[tools] does not pull it in"* for
    `firecrawl-py`. Somebody reasoned about exactly this hazard and fixed the
    case they noticed. Pydantic was missed **because** CrewAI does pull it in
    — the dependency is only hidden while it works, and the failure mode
    when the luck runs out is a v1/v2 API mismatch far from its cause.

37. ~~**[High] Render's static-site build pins no Node version.**~~
    **FIXED 2026-08-31.** `NODE_VERSION: "24"` is on the static site in
    `render.yaml`, matching what CI pins, with a comment saying to keep the two
    in step. `vite@8` requires `^20.19.0 || >=22.12.0`, so the floor is real and
    a platform default drifting below it fails the deploy rather than the tests.
    This is [gotchas](docs/gotchas-and-insights.md) 4 one layer up: the build environment that ships is
    the one verified least.

38. ~~**[Medium] `frontend/e2e/` is type-checked by nothing.**~~
    **FIXED 2026-08-31.** `{"path": "./e2e"}` is in the root `tsconfig.json`
    `references` array, so `tsc -b` now has the directory as a node in its build
    graph.

    **Proved by breaking it, not by assuming.** With the reference added, a
    deliberate `const x: number = "not a number"` in `studio.spec.ts` produced
    `e2e/studio.spec.ts(449,7): error TS2322` and was then reverted. Without the
    proof this is indistinguishable from the previous state, which is the whole
    trap: `tsc -b` builds a graph and an unreferenced config is simply not in
    it — no warning, no orphan diagnostic. It looked fine in an editor
    because a language server resolves the nearest config walking up from the
    open file, which is a different algorithm from the build's.

39. ~~**[Medium] `CREWAI_TRACING_ENABLED` is inverted between the two
    deploy paths.**~~ **NOT A BUG — the audit misread it.** Corrected
    2026-08-31; no value was changed, and changing one would have been the
    error.

    The two paths choose different **modes**, and
    `agents/08-observability.md:196` prescribes exactly this split:

    | path | value | mode |
    | --- | --- | --- |
    | `render.yaml` | `"true"` | **ephemeral** tracing — unauthenticated, short-lived links, not attributed to the AMP org. The documented Render answer. |
    | `Dockerfile` | `false` | off entirely, because the **authenticated** credential (`tokens.enc`) is a secret that expires and must never be baked into an image. |

    Flipping `render.yaml` to `false` on the strength of the audit would also
    have broken the Next Sequence's step 4, which calls for a paid acceptance
    run *"with traces enabled"*. Both comments now name which mode they are
    choosing and cross-reference the other, so the misreading is not available a
    second time.

    **One real finding fell out of checking it.** `CREWAI_TRACING_ENABLED=false`
    is **not a disable switch**: CrewAI's resolver has no branch returning
    `False` for it (`agents/08-observability.md:128-138`) — the value fails
    the `("true","1")` test and falls through to *stored consent*. The
    Dockerfile's `false` reads as off only because a fresh container has no
    stored `trace_consent`. Anything that ships a consent file would silently
    re-enable tracing with that line untouched. The Dockerfile now says so.

Item 34 below is **resolved** (see item 35 in the closed ledger) and is kept
only because its diagnosis is the valuable part. It appears after 36-39 because
those are the open ones; the numbering is chronological, not a priority order.

34. **A latent CrewAI defect in `or_()`, under investigation by another agent —
    do not assume a resolution here.** Both gates are declared
    `@listen(or_(scope_idea, revise_scope))` and
    `@listen(or_(synthesize, revise_verdict))` — multi-event `or_()`, non-router.
    CrewAI's `_find_triggered_methods` adds such a listener to
    `_fired_or_listeners` the first time it fires and thereafter **skips it**
    (`crewai/flow/runtime/__init__.py:3288-3297`, verified at 1.15.18):

    ```python
    should_check_fired = _is_multi_event_or(condition) and not is_router
    if should_check_fired and listener_name in self._fired_or_listeners:
        continue
    ```

    The consequence reported by the investigating agent is that an **in-process**
    revise reply makes the flow return normally having produced nothing: the
    router emits `scope_revise`, `revise_scope` runs, and the gate that should
    re-open is suppressed, so the flow simply ends.

    There *is* a re-arm path — `_rearm_or_listeners_for_trigger` (`:1067-1096`),
    called from `:3211-3216` when a router emits a fresh signal — but reading it,
    it only discards listeners whose condition **names the router's own emitted
    trigger**. `confirm_scope`'s condition names `scope_idea` and `revise_scope`,
    not `scope_revise`, so it is not a candidate.

    **The durable service path is unaffected, and the mechanism is sharper than
    "the attribute is not persisted".** On a `from_pending()` resume the
    replayed gate method never goes through `_find_triggered_methods`, so it is
    never entered into `_fired_or_listeners` at all — and because every gate
    raises `HumanFeedbackPending`, at most one revise can occur per resume leg.
    The durable path is structurally unable to reach the listener's second
    firing.

    **Resolved and closed — see item 35 in the closed ledger.** The entry above
    is kept because the diagnosis is the valuable part; the item was written
    while the fix was still being decided, and the decision has since been made,
    applied and proved.

#### Closed ledger

Kept because the *reasoning* is what stops the defect coming back.

35. **The in-process revise loop no longer drops the run.** Item 34's defect,
    fixed by `revise_scope` and `revise_verdict` each calling
    `self._discard_or_listener(FlowMethodName(...))` before they re-run their
    crew (`validator_flow.py`). Reproduced first, both candidate fixes
    prototyped against the real flow, then measured:

    | | happy | revise@scope | revise@verdict | topology |
    | --- | --- | --- | --- | --- |
    | baseline | pass | **fail** | **fail** | 14 nodes / 16 edges |
    | router variant | pass | pass | pass | **16 / 18**, new version hash |
    | `_discard_or_listener` | pass | pass | pass | 14 / 16, **byte-identical** |

    The router variant — moving the multi-event `or_()` onto a `@router`, which
    is exempt via `and not is_router` — is correct and was fully prototyped, but
    costs two pass-through nodes carrying no agent, no model and no decision,
    plus lockstep edits to `VALIDATOR_OVERLAY`, `mockGraph.ts`,
    `mockGraph.spec.ts`, `mockFrames.ts`, `edgeAnimation.spec.ts`,
    `crewStages.ts` and the E2E node/edge counts. Measured: applying it *without*
    the overlay edit took the suite from 537 OK to **378 run / 67 errors, 13
    modules unloadable**, because `graph.py:77-86` asserts an exact set match at
    import. `BranchSequencer`'s own docstring already refuses the mirror-image
    trade, so adding nodes to work around a CrewAI internal was the wrong side
    of a line this repo had already drawn.

    Depending on a private CrewAI method is the accepted cost, and it is
    bounded two ways. CrewAI's own cyclic-flow support leans on the same hook
    family — the runtime calls the coarser `_clear_or_listeners()` in three
    places and `ConversationalFlowMixin` declares it in a typed protocol
    (`conversational_mixin.py:279`, called at `:1148`). And
    `tests/validator/test_flow.py::InProcessGateReviseTests` pins both the
    behaviour and the hook: the behavioural test fails on revert with
    `Lists differ: ['confirm_scope'] != [...]` (verified by reverting), and the
    guard test's failure message names the router variant as the replacement.

18. **The stale schema docstrings are gone.** `Thread.points` / `num_comments`
    and `Repo.archived` no longer claim the tool envelopes "do not carry them
    yet"; the comments now explain why each is nullable and how the ladders read
    a `None` (`schemas/validator.py:175-220`).
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
    `_execute`'s tail reaches `_note_persistence_error`, which takes that lock —
    bounded by `RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS`. A resume that is still
    refused rolls back through `persistence.reopen_gate()` and answers **503**.
20. **The UI finishes a real run.** `events/serializer.py` emitted `RUN_STATE`
    for flow start and finish carrying only `{inputs}` / `{result}` — no
    `status` — while `applyRunState` read `details.status` alone, and nothing
    polls during a run. Every test double happened to send a status, and every
    frontend spec asserted against `event_type` values the backend **never**
    emits, so 116 green tests could not see it. Both drafts now carry `status`,
    both synthetic runners match the real shape, the client falls back to
    `event_type`, and the two sides are pinned by a committed fixture generated
    from the real serializer.
21. **A paused gate node shows as `waiting`.** `applyGate` sets it. Previously
    it set only the *run* status, and the node branch that would have done it
    was unreachable (item 12), so `confirm_scope` looked exactly like
    `revise_scope` at the moment the operator was being asked. The asymmetry was
    the tell: `gate_closed` had always set the same node to `completed`.
22. **`serve()` can run no-cost.** It hands uvicorn a factory *by name*, and a
    string factory drops kwargs, so the console script could previously only
    build the paid runners — anyone starting the service to look at the UI spent
    real money the moment they pressed Launch. `app_from_env()` reads
    `SYNTHETIC`.
23. **CORS middleware exists.** Invisible locally, where Vite's proxy makes
    everything same-origin; fatal in production, where the static site is a
    separate origin.
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
27. **Mock and live graphs agree.** `frontend/src/data/mockGraph.ts` uses the
    live Flow method ids and carries the routers, the revise loops and the
    quarantine node; `frontend/tests/mockGraph.spec.ts` (18 tests) asserts the
    node list and edge list against the live descriptor, in order.
28. **`downloadLogs` is tested.** jsdom 30 implements the blob URL store, so
    `frontend/tests/downloadLogs.spec.ts` (10 tests) exercises minting,
    revoking, percent-encoding, the ZIP name and the failure paths for real;
    only the anchor `click` is stubbed.
29. **WebSocket gate replies** land through the same compare-and-set path as
    HTTP (`service/app.py::handle_gate_reply`), bounded by the three `WS_*`
    limits.
30. **Brief Crew has a regression test** covering the Track A/B behaviour the
    platform rules forbid regressing.
31. **The header no longer reads "Offline" on a working page.** This was item
    10. `connection` binds the WebSocket, and no socket exists until a run
    starts, so "the backend is down" and "you have not launched anything yet"
    were the same word on the first thing a visitor reads — which is also what
    made the silent mock fallback ([gotchas](docs/gotchas-and-insights.md) 2) so hard to spot.
    `connectionLabel` now reports the probed transport.

    Two things it deliberately does not do. **Nothing polls the API**, so a
    backend that dies between page load and Launch still reads `ready` — this
    fixes the label, not the absence of a health probe. And the badge's CSS
    class is still bound to the raw ref, not the label, so a `ready` or
    `connecting` word carries `is-offline` and renders in the muted default
    rather than the warn colour. Cosmetic, but colour and word can now disagree.
32. **A run that is executing when the process restarts is no longer orphaned.**
    This was observed in production, not theorised: run
    `e0b3b65e-9398-45e9-a9e5-3d72053be28d` streamed 102 frames, last reconnected
    at 04:05:49 on 2026-08-30, and still reported `status: "running"` hours after
    the API restarted for the `5daf401` redeploy. Both Render services carry
    `autoDeploy: yes`, so **every push to `main` restarts the API**.

    `d3523c5` decided the question the fix required, and decided it *against*
    CrewAI rather than by assumption: `from_pending` raises without a
    `pending_feedback` row, and that row is written only when
    `HumanFeedbackPending` is raised — so a run interrupted *mid-method* carries
    no resumable checkpoint and cannot be recovered. Such a run is now **failed**
    at startup and by a periodic sweep, with a reason the operator can act on,
    and `cancelling` reaches `CANCELLED`. The one shape that **is** resumable — a
    crash between `open_gate` and `mark_waiting`, where both durable anchors
    survive — is adopted back to `WAITING` instead. `VALIDATOR_ORPHAN_RUN_RECOVERY`
    / `VALIDATOR_ORPHAN_RUN_GRACE_SECONDS`; 22 tests. Related: there is still no
    retention or purge, so terminal rows accumulate.
33. **The console shows the run's conclusion.** The backend had always delivered
    it — `GET /api/runs/{id}` returns `result`, and the terminal frame carries
    `details.result` — and the client discarded it at **three** separate layers,
    so a completed run showed strictly *less* than a mid-flight one:
    `StudioApi.getRun` dropped `result` when normalising the snapshot, the
    composable had no `report` ref for it to land in, and `applyRunState` ignored
    `frame.details.result`. `types/studio.ts` gained `RunResult`,
    `useValidatorRun.ts` gained `report` + `captureResult`, and `ReportPanel.vue`
    renders it, opening itself the first time a body arrives (keyed on run id, so
    a relaunch re-arms) because "the final output is visible" cannot depend on
    the operator knowing to look for a button.

    A second loss sat next to it: `gate_closed` nulled `pendingGate`, and the
    verdict gate card was **the only place the score was ever rendered** — so
    answering the gate destroyed the run's conclusion. `closeGate()` now captures
    `verdictSummary` the moment before the card disappears, and leaves it
    untouched when a *scope* gate closes.

    **Why 133 green tests could not see any of this:**
    `SyntheticValidatorRunner._finish` returned a result with **no body at all**,
    so report rendering was *untestable* on the free path — no unit test, no E2E
    test and no local synthetic run could ever exercise it. The double now
    returns a `ValidationReport`-shaped result with a real `markdown_body`. A
    double that diverges from its subject certifies nothing; that is the lesson,
    and it is the same one as item 20.

## Recommended Next Sequence

Deployment, admission control and CI are all settled. What is left is one human
decision, one CrewAI decision, and then money.

1. **Read the five ladders in `RUBRIC_ANCHORS`** (item 5), with
   `docs/rubric-review.md` beside them and the knowledge that its two Criticals
   are now fixed and its F4 is not. This is a decision only a human can make and
   it is still blocking: the service is one Launch away from scoring a real idea
   against a rubric nobody has approved. Take F4 — the tool-label coupling —
   first, and decide *accept / fix / accept-with-eyes-open*. An anchor edit
   surfaces in `tests/validator/test_crews.py` and `test_guardrails.py`, which
   assert anchor text and support bounds directly, so nothing changes silently.
2. **Settle item 34 (the `or_()` suppression) before any run that might
   revise.** Another agent is investigating; do not duplicate the work, and do
   not assume the durable path's immunity generalises. Whatever is decided,
   item 15 (`SyntheticValidatorRunner` ignoring `decision`) is **done** — the
   double now branches on the reply, so the revise loop is exercised end to
   end on the free path for the first time.
3. **Add a `LICENSE`** (item 17). The repo is public with no licence file, which
   means all rights reserved — almost certainly not the intent — and
   `pyproject.toml` already carries the note saying so.
4. **Run one real idea through both gates on the deployed service, with traces
   enabled**, and inspect citation closure before sharing any trace link. This
   is what actually closes item 1 and puts real concurrent load on PG 18
   (item 3). Do it only after step 1. Note the three defects the *first* paid
   run found are now fixed but have never been re-exercised live: the
   un-truncated report body, the priced calls, and the keyword-shaped queries
   are all still unproven against real tools.
5. **Run the live benchmark** (item 2) once a real run is known to work.
6. **Re-test two-process gate contention against PG 18** — the one thing a
   single real run cannot exercise, and the only untested half of item 3. There
   are now **four** compare-and-set paths that have never met a concurrent
   writer, the orphan sweep being the newest.

Cheap cleanups that need no decision and no money, all re-verified open on
2026-08-30: item 11's missing `maxlength` is one attribute next to a character
counter that already exists; item 12's three dead branches are a few lines;
item 14 (the unhonoured `ETag` — no `If-None-Match` reader exists anywhere in
`src/brief_crew/`) is a small handler change; item 7's missing
`<link rel="icon">` is one line of `index.html` and stops a 404 on every page
load.

**Items 36-38 are DONE (2026-08-31)**, along with the cheap cleanups: the
declared `pydantic`/`pyyaml`, `NODE_VERSION: "24"`, the `./e2e` tsconfig
reference, the honoured `ETag`, the bounded and recoverable idea box, and the
favicon link. Item 39 turned out not to be a bug at all — see its entry.

What that leaves before step 4 is only what it always was: **read the rubric**.
Nothing in the cleanup sweep touched a scoring decision, and nothing in it can.

## OpenRouter MCP - the live catalogue, and what it settles

Added 2026-09-01. The `openrouter` MCP server is registered on this project and
its 22 tools are the authority on every model fact this file would otherwise
restate and let drift. **Consult them before touching `CHEAP_MODEL`,
`ESCALATION_MODEL`, `PRICES`, a `reasoning_effort` argument, or any prompt-level
cost decision.** The lesson this document keeps re-learning - a number written
into prose is wrong within two commits - has an actual fix here: do not quote a
price, look it up.

### Access, and the weekly cliff

The credential is OAuth, lasts **exactly 7 days, and carries no refresh token**,
so it dies every week and cannot renew itself. While it is stale the harness
hides the real tools and offers `mcp__openrouter__authenticate` /
`complete_authentication` in their place. Call `authenticate`, open the URL it
returns, and the real tools swap in **mid-session - `claude mcp login` and a
restart are NOT needed.** Prove it with `mcp__openrouter__ping` -> `pong`.

**If a future session sees no `mcp__openrouter__*` tools, the token has
expired.** That is a stale credential, not a missing capability - the same
distinction [gotchas](docs/gotchas-and-insights.md) keeps drawing about
`pkill` and about a green suite.

### Which tool answers which question

**Free. Read-only, no tokens billed:**

| Tool | Use it for |
| --- | --- |
| `get-model` | one model's live price, context, `supported_parameters`, and `reasoning` defaults |
| `list-models` | catalogue search. `min_tool_success_rate`, `min_agentic_index` and `max_price` are the filters that matter for the three tool-using research analysts on the cheap tier |
| `list-model-endpoints` | the **per-provider** price / latency / throughput spread behind one slug - the only way to bound what `:nitro` actually bills |
| `get-endpoint-uptime-history` | which provider degraded during a window (72h of history) |
| `list-providers` | provider slugs, for routing allow/deny |
| `list-benchmarks` | Artificial Analysis intelligence / coding / agentic indices, Design Arena ELO |
| `list-daily-model-rankings`, `list-task-classifications`, `list-app-rankings` | what real traffic actually uses for a given kind of work |
| `get-generation` | the **actual** cost, token counts and serving provider for one generation id |
| `get-credits` | remaining balance. Run before a paid acceptance run; never write the figure into a doc - `docs/preflight.md` already adopted that rule |
| `search-docs` | current OpenRouter API usage |
| `list-presets` / `get-preset` | saved dashboard configs |

**These SPEND MONEY. Never in a test, never casually:** `send-message` (a real
completion), `generate-image`, `generate-speech`, `transcribe-audio`, and
`spawn-ori-eval` (runs a real agent over real prompts). `send-message` is the
right instrument for the Reporter/Scoper A/B still open as remaining-work item 4
(Q4) - set `max_tokens`, which its own schema calls the single most effective
brake on a reasoning model - but it bills the account `get-credits` reads.

### What one pass of these tools found, 2026-09-01

Measured against the live catalogue, not argued:

- **`PRICES` is correct to the cent.** `google/gemini-3.5-flash-lite` is
  $0.30 / $2.50 and `google/gemini-3.7-flash` is $0.75 / $3.75 live, matching
  `config.py:56-59` exactly. The platform rule that a model swap edits `PRICES`
  in the same commit has held.
- **But `:nitro` is not bounded by that number.** `config.py:44-47` says the
  recorded price "is the published floor and the effective rate may be higher".
  `list-model-endpoints` says it is not the floor either: **eight** endpoints
  serve `gemini-3.5-flash-lite`, from **$0.15 / $1.25** (`flex`) to
  **$0.54 / $4.50** (`priority`) - a 3.6x spread with $0.30 / $2.50 sitting in
  the middle. `:nitro` routes on speed, not price, so a real run can bill up to
  **80% above** what `compute_cost_usd` estimates. Bounding that is one tool
  call rather than a guess, and it should be done before item 1's acceptance run
  is priced.
- **`get-generation` cannot reconcile anything yet.** It returns OpenRouter's
  own per-generation cost - precisely the figure section 8 says "never reaches
  the process" - but **nothing captures a generation id**: grepped across
  `events/` and `service/` on 2026-09-01, zero hits. Capturing it is the
  prerequisite for turning that documented estimate into a measurement, and it
  is the cheapest route to closing the cost half of item 1.
- **The Synthesist is probably NOT running at `reasoning_effort=high`.**
  `config.py:874`, `:1018` and `:1037` all describe it that way inside cost
  arguments, while `config.py:628` and
  `crews/validator_crew/validator_crew.py:344` both record that
  `LLM(reasoning_effort=...)` is silently dropped for every OpenRouter model.
  Live, `gemini-3.7-flash` reports `reasoning.mandatory: true` with
  `default_effort: "medium"`. So the effort is the provider default and the
  prose overstates the spend. Related: reasoning tokens bill at the completion
  rate on **both** tiers, which is the only reason the two-tuple `PRICES` shape
  stays honest - that is a coincidence of Google's pricing, not a property of
  the design, and a future model whose `internal_reasoning` rate differs would
  break the estimate silently.

## CrewAI Traces

For behavior debugging, enable CrewAI traces before a live run:

```powershell
crewai traces enable
crewai run
```

Traces can include prompts, task inputs/outputs, tool arguments/results, and model responses. Confirm that no secrets or personal data were processed before sharing a trace URL.
