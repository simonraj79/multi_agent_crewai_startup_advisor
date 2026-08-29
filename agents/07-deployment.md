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
> **Not yet built:** the Postgres schema, the SQLAlchemy layer, the FastAPI
> `POST /runs` / `GET /runs/{id}` service, and `render.yaml` itself. `persist`
> currently writes `output/brief.md` and a `output/last_run.json` run record —
> the same fields the `runs` / `run_metrics` tables want, so moving it to
> Postgres is a change of destination, not of shape. The two Render web services
> remain deliberately uncreated.
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
| Render Postgres | `agentic-crew-ai-db` · `dpg-da94gqhf2nfc73e8rh7g-a` | `basic_256mb` · PG 17 · 1 GB | singapore | **live** |
| Render backend | `agentic-crew-ai-api` | `starter` | singapore | **not created** |
| Render frontend | `agentic-crew-ai-web` | static | singapore | **not created** |

The two web services are deliberately **not** created. Render deploys web
services from a git repository, and there is no repo or application code yet.
Creating them now would produce two failing services billing $7/mo each. Push the
code, then apply the Blueprint below.

Render owner ID: `tea-csps46i3esus73eojjp0`.

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

```yaml
databases:
  - name: agentic-crew-ai-db
    plan: basic_256mb
    region: singapore
    diskSizeGB: 1
    postgresMajorVersion: "17"

services:
  - name: agentic-crew-ai-api
    type: web
    runtime: python
    plan: starter
    region: singapore
    buildCommand: "uv sync"
    startCommand: "uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT"
    healthCheckPath: /healthz
    maxShutdownDelaySeconds: 300
    envVars:
      - key: PYTHON_VERSION
        value: "3.13"
      - key: DATABASE_URL
        fromDatabase:
          name: agentic-crew-ai-db
          property: connectionString
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

  - name: agentic-crew-ai-web
    type: web
    runtime: static
    region: singapore
    buildCommand: "npm ci && npm run build"
    staticPublishPath: dist
    envVars:
      - key: VITE_API_BASE_URL
        fromService:
          name: agentic-crew-ai-api
          type: web
          property: host
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
```

Notes:

- `sync: false` means the value is never committed — Render prompts once at
  Blueprint creation and stores it as a dashboard secret. **Every API key uses
  it.** The only literals here are non-secret configuration.
- `uv` is natively supported: Render auto-detects `uv.lock` at the repo root.
  Pin the version with `UV_VERSION` if you need determinism.
- Python version comes from `PYTHON_VERSION` or a `.python-version` file. Pin it —
  services created after Feb 2026 otherwise default to 3.14, which `crewai`
  excludes (`requires-python <3.14`). **This would fail the build.**
- A static site costs nothing, so the frontend adds no fixed cost.
- Region is immutable after creation. `singapore` matches both the Postgres
  instance and the Pinecone index.

---

## Deployment checklist

Status as of 2026-08-29. Steps 1 and 2's prerequisites are met; nothing has been
deployed.

| | Step | Status |
|---|---|---|
| 1 | `.env` carries all five credentials plus `PINECONE_INDEX_NAME` | ✅ verified — all four live services answered. The `FIRECRWALL_API_KEY` typo is fixed. |
| 2a | **`uv.lock` exists at the repo root** | ✅ written by `crewai install` (874 KB). Render auto-detects it. |
| 2b | `.python-version` pins 3.13 | ✅ — this is step 4's failure, pre-empted |
| 2c | `git init`, commit, push to GitHub | ❌ **not a repo yet.** This is the first blocker: Render deploys from git, and there is nothing to deploy from. |
| 3 | Create the Blueprint from `render.yaml` | ❌ `render.yaml` is specified above but **not written to disk** |
| 4 | Confirm backend picked up Python 3.13, not 3.14 | ⏸️ blocked on 3 |
| 5 | Apply the SQL schema to `agentic-crew-ai-db` | ❌ schema is specified above, never applied. The database is live and empty. |
| 6 | Smoke-test `POST /runs` | ❌ no FastAPI service exists |
| 7 | Check `run_metrics.successful_requests` populates | ⏸️ blocked on 5 and 6 — **but the number itself already exists**, see below |

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
