# 07 · Deployment — Flow, Postgres, Render

Track B: the hosted service. Provisioned resources are real and live as of
2026-08-29.

> 🔨 **The Flow is implemented** in `src/brief_crew/main.py`, with the method
> names this file specifies: `retrieve_cached` → `check_cache` → `scrape_web` →
> `index_content` → `write_brief` → `persist`. Thresholds are imported from
> `brief_crew.config`, not restated, so they cannot drift from `06`.
>
> `.python-version` pins **3.13** at the repo root, which is the build failure
> this file warns about (services created after Feb 2026 default to 3.14, which
> `crewai` excludes).
>
> 🔨 **The service is built.** `src/brief_crew/service/` now contains the FastAPI
> + WebSocket application (`app.py`, factory `create_app`), the SQLAlchemy
> persistence layer (`persistence.py` — flow states, pending feedback, runs,
> node metrics, ordered frames, human gates, PostgreSQL or SQLite), the run
> registry and the flow runners. The endpoint surface is wider than the
> `POST /runs` / `GET /runs/{id}` pair sketched below; see `CLAUDE.md` §9.
> `render.yaml`, `Dockerfile`, `.dockerignore` and `.github/workflows/ci.yml`
> now exist at the repo root.
>
> **Still not done:** the raw `runs` / `run_metrics` / `run_sources` DDL below is
> *not* what ships — `persistence.py` owns its own SQLAlchemy tables — so treat
> that SQL as design intent, not as a migration to apply. Brief Flow `persist`
> still writes `output/brief.md` and `output/last_run.json`. The two Render web
> services remain deliberately uncreated, and the Blueprint has not been applied.
>
> One gap this file should record: crew-level `token_usage` is **not split by
> model**, so the cost figure in `last_run.json` is an upper bound priced at the
> escalation tier. The per-agent split needs a `BaseEventListener` on
> `LLMCallCompletedEvent`, which carries `model`, `task_id` and `agent_id`.

---

## Provisioned

| Resource | Identifier | Plan | Region | Status |
|---|---|---|---|---|
| Pinecone index | `agentic-crew-ai-index` | serverless | aws ap-southeast-1 | **live** |
| Render Postgres | `agentic-crew-ai-db` · `dpg-da94gqhf2nfc73e8rh7g-a` | `basic_256mb` · **PG 18** · 1 GB | singapore | **live** |
| Render backend | `agentic-crew-ai-api` | `starter` | singapore | **not created** |
| Render frontend | `agentic-crew-ai-web` | static | singapore | **not created** |

The database version was verified against the Render API on 2026-08-29: it
reports **PostgreSQL 18**, not the 17 this document previously recorded. The
`postgresMajorVersion` in the Blueprint was corrected to match; a mismatch there
is not cosmetic, because Render treats the major version as part of the resource
definition.

The two web services are deliberately **not** created. Creating them before the
Blueprint is ready would produce two failing services billing $7/mo each. The
application code and `render.yaml` now exist and the repository has a baseline
commit, so the remaining prerequisite is a git **remote** — Render deploys from a
hosted repository, and none is configured yet (`git remote -v` is empty).

Render owner ID: `tea-csps46i3esus73eojjp0`.

`agentic-crew-ai-db` was created by hand, outside any Blueprint. Applying
`render.yaml` will not silently adopt it: confirm on the Blueprint preview that
Render is **linking** the existing instance rather than proposing a second
database before you approve the apply.

### Running cost

| Item | $/mo |
|---|---|
| Postgres `basic_256mb` + 1 GB | 6.30 |
| Backend web service `starter` | 7.00 |
| Frontend static site | 0.00 |
| Pinecone serverless | usage-based, negligible at this scale |
| **Total fixed** | **~$13.30** |

Not included: OpenRouter tokens, Firecrawl calls, Cohere rerank units.

---

## Flow architecture

The one genuinely dynamic decision in this system is cache hit versus miss. A
`@router` resolves it deterministically, for **zero LLM calls**.

```
@start()                                    retrieve_cached
                                            Pinecone query + Cohere rerank

@router(retrieve_cached)                    check_cache
                                            "cache_hit" | "cache_miss"
                                            threshold check — no model

@listen("cache_miss")     scrape_web        Researcher agent, Firecrawl tools
@listen(scrape_web)       index_content     chunk / embed / upsert — plumbing

@listen(or_("cache_hit", index_content))
                          write_brief       Analyst then Writer

@listen(write_brief)      persist           brief.md + Postgres row
```

The router's three thresholds — **≥3 reranked hits**, **top `rerank_score` ≥
0.30**, **`indexed_at` ≤ 60 days** — are specified once, in
`06-retrieval-layer.md` → "The staleness gate". Do not restate them in code
comments; import them from one module-level constant so they cannot drift.

The `@start` method is `retrieve_cached`, distinct from the `retrieve_and_rerank`
**tool** it calls (`06-retrieval-layer.md`). `08-observability.md` §7 matches on
the router method name `check_cache` to populate `runs.route`.

Why a Flow rather than `Process.hierarchical`: a Manager agent would make the
identical binary decision and charge an LLM call per run to do it. See
`04-manager.md` — the comparison is now concrete rather than hypothetical.

Why a Flow rather than `Process.sequential`: sequential cannot branch at all. The
cache-hit path must skip scraping entirely, and that is not expressible as task
ordering.

Flows also mix plain Python and agent calls freely, which matters here — Pinecone,
Cohere and Postgres calls have no business being wrapped in agent personas, and a
`Crew` would force exactly that.

### State

Use a Pydantic `Flow` state carrying `topic`, `retrieved` (chunks), `route`
(`cache_hit`/`cache_miss`), `scraped`, `brief`, `usage`. `@persist` backs state with SQLite
at `db_storage_path()/flow_states.db` — ephemeral on Render. Only enable it if
you need pause/resume; otherwise the Postgres run record below is the durable
artifact.

---

## Postgres schema

Owned by application code through SQLAlchemy. **Not** routed through CrewAI —
CrewAI has no Postgres backend for anything (see `00-shared-config.md` §7).

```sql
CREATE TABLE runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    topic           text        NOT NULL,
    status          text        NOT NULL,   -- queued|running|succeeded|failed
    route           text,                   -- cache_hit|cache_miss
    brief_markdown  text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    completed_at    timestamptz,
    error           text
);

CREATE TABLE run_metrics (
    run_id              uuid REFERENCES runs(id) ON DELETE CASCADE,
    successful_requests int,     -- CrewOutput.token_usage.successful_requests
    prompt_tokens       int,
    completion_tokens   int,
    total_tokens        int,
    cost_usd            numeric(12,6),   -- COMPUTED: tokens × 00-shared-config §3 price table
    PRIMARY KEY (run_id)
);

CREATE TABLE run_sources (
    id          bigserial PRIMARY KEY,
    run_id      uuid REFERENCES runs(id) ON DELETE CASCADE,
    url         text NOT NULL,
    publisher   text,
    from_cache  boolean NOT NULL,   -- provenance: retrieved vs freshly scraped
    rerank_score real
);
```

`run_metrics` is what makes the cost comparison in the lecture's slide-62 stretch
a query rather than an anecdote. `run_sources.from_cache` is what lets the Writer
be honest about provenance — see `03-writer.md`.

Populate it from `Flow.usage_metrics` (which already aggregates every kickoff in
a run) plus a `BaseEventListener` on `LLMCallCompletedEvent` for the per-agent
split. `runs.route` comes free from `MethodExecutionFinishedEvent.result` on the
router method. Listener patterns, and the concurrency caveat about the bus being
a process-wide singleton, are in `08-observability.md` §7.

**`cost_usd` must be computed** from token counts × the price table in
`00-shared-config.md` §3 — CrewAI discards OpenRouter's cost field before it
reaches any event.

### Observability on Render

`CREWAI_TRACING_ENABLED=true` is set in the Blueprint, but traces from Render
will be **ephemeral** (not attributed to your AMP org): the tracing credential
lives in an encrypted file written by an interactive `crewai login`, there is no
env-var equivalent, and it expires with no refresh. Do not bake `tokens.enc` into
the image. Authenticated tracing is a local/dev capability; Postgres is the
production record. Full reasoning in `08-observability.md` §3.

---

## Long-running work

A crew run takes minutes. Render's web service sits behind a proxy not designed
to hold a request open that long, so the HTTP layer must not block on it.

```
POST /runs        -> insert row (status=queued), return 202 + run_id
GET  /runs/{id}   -> poll status; returns brief when succeeded
```

Two options for the execution itself:

| Option | Cost | Trade |
|---|---|---|
| **In-process background task** | $0 extra | Simplest. Dies on redeploy — Render sends `SIGTERM` then `SIGKILL` after `maxShutdownDelaySeconds` (default 30s, max 300s). A mid-flight run is lost. |
| **Separate Background Worker** polling the `runs` table | +$7/mo | Survives backend redeploys, scales independently. No extra queue infrastructure — Postgres is the queue. |

Start with the in-process task, given one concurrent run is the memory ceiling
anyway (§2 of `00-shared-config.md`: ~210 MB baseline against 512 MB). Move to a
worker when concurrency or redeploy-safety actually matters, and raise
`maxShutdownDelaySeconds` either way.

**Do not fan out `kickoff_async`** in request handlers: it is
`asyncio.to_thread(self.kickoff, ...)`, so each concurrent run holds a thread-pool
slot and ~210 MB. Construct a fresh `Crew` per run rather than sharing one.

---

## `render.yaml`

⚠️ The authoritative copy is now **`render.yaml` at the repo root**. The block
below is a summary of it; if the two disagree, the file wins. Three errors in the
version this document used to print are corrected — see "Corrections" below.

```yaml
databases:
  - name: agentic-crew-ai-db
    databaseName: agentic_crew_ai_db
    user: agentic_crew_ai_db_user
    plan: basic_256mb
    region: singapore
    diskSizeGB: 1
    postgresMajorVersion: "18"

services:
  - name: agentic-crew-ai-api
    type: web
    runtime: python
    plan: starter
    region: singapore
    buildCommand: "uv sync --frozen --extra service"
    startCommand: "uv run --no-sync uvicorn brief_crew.service.app:create_app --factory --host 0.0.0.0 --port $PORT"
    healthCheckPath: /healthz
    maxShutdownDelaySeconds: 300
    envVars:
      - key: PYTHON_VERSION
        value: "3.13"
      - key: DATABASE_URL
        fromDatabase:
          name: agentic-crew-ai-db
          property: connectionString
      - key: RUN_CONCURRENCY
        value: "1"             # one run is the 512 MB memory ceiling
      - key: CREWAI_DISABLE_TELEMETRY
        value: "true"
      - key: CREWAI_TRACING_ENABLED
        value: "true"          # ephemeral traces only — see 08-observability.md §3
      - key: CREWAI_STORAGE_DIR
        value: "/tmp/crewai"   # pin it; otherwise it derives from the CWD name
      - key: PINECONE_INDEX_NAME
        value: agentic-crew-ai-index
      - key: OPENROUTER_API_KEY
        sync: false
      - key: FIRECRAWL_API_KEY
        sync: false
      - key: PINECONE_API_KEY
        sync: false
      - key: COHERE_API_KEY
        sync: false
      - key: GITHUB_TOKEN
        sync: false            # optional — raises GitHub search 8/min → 24/min

  - name: agentic-crew-ai-web
    type: web
    runtime: static
    rootDir: frontend
    buildCommand: "npm ci && npm run build"
    staticPublishPath: dist
    envVars:
      - key: VITE_API_URL
        sync: false            # full origin incl. scheme, e.g. https://…onrender.com
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
```

### Corrections against the earlier draft of this block

| Was | Is | Why |
|---|---|---|
| `postgresMajorVersion: "17"` | `"18"` | The live instance reports PG 18. Verified against the Render API, 2026-08-29. |
| `startCommand: uv run uvicorn app.main:app …` | `uv run --no-sync uvicorn brief_crew.service.app:create_app --factory …` | There is no `app.main` module. The real ASGI entry point is a **factory** — `create_app` — so `--factory` is mandatory. `serve()` at the bottom of `src/brief_crew/service/app.py` confirms the target and the `factory=True` flag; it differs only in binding (see the note on `HOST` below). |
| `buildCommand: uv sync` | `uv sync --frozen --extra service` | fastapi, sqlalchemy and `psycopg[binary]` are in the **optional** `service` extra. A bare `uv sync` omits all three (it does pull `uvicorn` transitively, which makes the failure look like a runtime bug rather than a missing dependency) and `create_app` raises `ServiceDependencyError` at import. |
| `VITE_API_BASE_URL` via `fromService … property: host` | `VITE_API_URL`, `sync: false` | The frontend reads `VITE_API_URL` (`frontend/src/services/studioApi.ts`). It is also the base of `new URL(...)` for the WebSocket, so a bare hostname resolves as a relative path and `/ws` never connects. It needs the full `https://…` origin, which `fromService` cannot produce. |
| static site: `region: singapore` | omitted | Static sites are served from a global CDN; the region pin is meaningful only for the API and the database. |
| static site: no `rootDir` | `rootDir: frontend` | `package.json` lives in `frontend/`, not the repo root. `staticPublishPath` is then relative to `rootDir`. |

Notes:

- `sync: false` means the value is never committed — Render prompts once at
  Blueprint creation and stores it as a dashboard secret. **Every API key uses
  it.** The only literals are non-secret configuration.
- `uv` is natively supported: Render auto-detects `uv.lock` at the repo root.
  Pin the version with `UV_VERSION` if you need determinism.
- `--frozen` on the build installs exactly what `uv.lock` pins, with no
  re-resolution. `--no-sync` on the start command stops `uv run` from re-syncing
  at boot — an implicit sync there would compute the default dependency set and
  **remove** the `service` extra the build just installed.
- `serve` (the `[project.scripts]` console entry, `brief_crew.service.app:serve`)
  is *not* used as the start command. It honours `$PORT` but defaults `HOST` to
  `127.0.0.1`, which Render's proxy cannot reach. Either invoke uvicorn
  explicitly, as above, or set `HOST=0.0.0.0` in the environment first.
- Python version comes from `PYTHON_VERSION` or a `.python-version` file. Pin it —
  services created after Feb 2026 otherwise default to 3.14, which `crewai`
  excludes (`requires-python <3.14`). **This would fail the build.**
- `maxShutdownDelaySeconds: 300` is Render's ceiling, not a comfortable margin.
  On `SIGTERM` the FastAPI lifespan calls `RunRegistry.close()`, which does
  `executor.shutdown(wait=True, cancel_futures=True)`: queued runs are cancelled,
  but an already-executing CrewAI step is waited on, and a full six-agent
  validator run can exceed five minutes. Frame flushing itself is cheap — a
  bounded queue drain plus a 5-second writer-thread join. A redeploy mid-run can
  still be `SIGKILL`ed; durable persistence and resume are the mitigation.
- A static site costs nothing, so the frontend adds no fixed cost.
- Region is immutable after creation. `singapore` matches both the Postgres
  instance and the Pinecone index.

---

## Container alternative

`Dockerfile` and `.dockerignore` at the repo root build the **API only** — the
frontend stays a static site. Two stages: `uv sync --frozen --extra service`
into `/app/.venv`, then a slim runtime that adds `libgomp1` (onnxruntime, pulled
in transitively by chromadb via `crewai[tools]`, needs it and `python:*-slim`
does not ship it) and runs as a non-root user. The project is installed
**editable**, so `src/` must live at the same absolute path at runtime as at
build time; both stages use `/app`.

`.dockerignore` excludes `.env`, `.venv/`, `node_modules/` (via `frontend/`),
`output/`, `.git/` and **`tokens.enc`** — the CrewAI AMP tracing credential, a
secret that expires and must never reach an image (see `08-observability.md` §3).
`CREWAI_TRACING_ENABLED` therefore defaults to `false` in the image.

The image has **not** been built or run: no Docker daemon was available on the
machine where it was written.

---

## CI

`.github/workflows/ci.yml` runs the checks that cost nothing, on every push and
pull request:

| Job | Command | Notes |
|---|---|---|
| `python` | `uv sync --frozen --extra service` then `python -m unittest discover -s tests -t . -v` | Python pinned to 3.13. 65 tests, all external services mocked. Also parses `render.yaml`. |
| `frontend` | `npm ci && npm run build` in `frontend/` | `npm run build` is `vue-tsc -b && vite build`, so type-check and build in one step. Node 24. |

**Do not add a CI step that needs a paid credential.** The suite is deliberately
free to run — CrewAI crews, OpenRouter, Pinecone, Cohere, Firecrawl, Hacker News
and GitHub are all replaced with mocks or deterministic test doubles — and a live
acceptance run belongs in a manual, explicitly-approved workflow.

---

## Deployment checklist

Status as of 2026-08-29, after the F44 deployment-artifact pass. Everything that
can be done locally is done; nothing has been deployed.

| | Step | Status |
|---|---|---|
| 1 | `.env` carries all five credentials plus `PINECONE_INDEX_NAME` | ✅ verified — all four live services answered. The `FIRECRWALL_API_KEY` typo is fixed. |
| 2a | **`uv.lock` exists at the repo root** | ✅ written by `crewai install` (874 KB). Render auto-detects it. `uv sync --frozen --extra service` resolves against it cleanly (dry-run verified). |
| 2b | `.python-version` pins 3.13 | ✅ — this is step 4's failure, pre-empted |
| 2c | `git init`, commit, push to GitHub | ⚠️ **partly done.** The repo exists with a baseline commit on `master`. `git remote -v` is empty — **no remote, nothing pushed.** This is now the first blocker. |
| 2d | `render.yaml` written to disk | ✅ at the repo root, with the PG 18 / factory start command / `--extra service` / `VITE_API_URL` corrections listed above |
| 2e | `Dockerfile` + `.dockerignore` | ✅ at the repo root. Never built — no Docker daemon available. |
| 2f | CI workflow | ✅ `.github/workflows/ci.yml`: unittest on Python 3.13 plus the frontend build. No paid credential. Never executed on GitHub — see 2c. |
| 3 | Create the Blueprint from `render.yaml` | ❌ **not applied.** Writing the manifest is not applying it; this is a deliberate manual step. Check the preview links the existing database rather than creating a second one. |
| 4 | Confirm backend picked up Python 3.13, not 3.14 | ⏸️ blocked on 3 |
| 5 | Apply the SQL schema to `agentic-crew-ai-db` | ✅ **no longer a manual step.** `PostgresFlowPersistence.init_db()` runs `metadata.create_all()` at construction. The shipped tables are `flow_states`, `pending_feedback`, `runs`, `run_node_metrics`, `run_frames`, `run_gates` — **not** the `runs` / `run_metrics` / `run_sources` DDL sketched above, which is now design intent only. Never exercised against a real PostgreSQL instance. |
| 6 | Smoke-test the service | ⚠️ locally only. `uvicorn brief_crew.service.app:create_app --factory --host 0.0.0.0` boots and `GET /healthz` and `GET /readyz` both return 200 with no credentials set. Not smoke-tested on Render. |
| 7 | Check per-run token metrics populate | ⏸️ blocked on 3 — the numbers exist locally, see below |

### What already works, and what moving to Postgres actually costs

Step 7's number is not waiting on deployment. `persist` writes it to
`output/last_run.json` today, in the shape the tables want:

```json
{ "run_id": "...", "topic": "...", "route": "cache_miss",
  "successful_requests": 13, "prompt_tokens": 109104,
  "completion_tokens": 30085, "total_tokens": 139189,
  "cost_usd_upper_bound": 0.19464675 }
```

`run_id` / `topic` / `route` are the `runs` columns; the rest are `run_metrics`.
So step 5 plus a SQLAlchemy write in `persist` is a change of **destination**,
not of structure — the hard part (deciding what to record, and computing cost
from tokens because OpenRouter's figure never reaches us) is done.

Two honest caveats before anyone treats that JSON as production-ready:

- **`cost_usd_upper_bound` is not `cost_usd`.** The schema above declares
  `cost_usd numeric(12,6)`. What exists is an upper bound priced entirely at the
  escalation tier, because crew-level `token_usage` is not split by model. Writing
  it into a column named `cost_usd` would launder an estimate into a measurement.
  Either rename the column or land the `LLMCallCompletedEvent` listener first —
  see `08-observability.md`.
- **`run_sources` cannot be populated at all yet.** Its `url` and `from_cache`
  columns need per-source provenance, and write-back currently indexes the
  Researcher's notes with `url=""`. Same listener fixes it. See `06`.

### Running it today

`crewai run` is the Flow entry point — `pyproject.toml` declares
`[tool.crewai] type = "flow"`, and `[project.scripts] kickoff` resolves to
`brief_crew.main:kickoff`. Verified end to end: route `cache_miss`, 13 calls,
3 chunks written back, `output/brief.md` and `output/last_run.json` produced.

⚠️ `crewai run` **block-buffers stdout** when output is redirected to a file, so
the `[flow]` progress lines arrive in chunks rather than streaming. Harmless
locally; worth knowing before you read a redirected log and conclude a run has
hung. `python -u` streams properly if you need live progress.
