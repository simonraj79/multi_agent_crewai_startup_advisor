# Deploying to Render

What to do after the repository is pushed. Everything here is a manual step —
[`render.yaml`](../render.yaml) is a manifest, and writing a manifest is not the
same as applying it.

Source of truth for the resource decisions is
[`agents/07-deployment.md`](../agents/07-deployment.md). This file is the ordered
procedure; that one is the reasoning.

---

## Before you start

> ### ⚠️ Settle the account identifiers before the first push
>
> Redacting a value in the working tree does not remove it from git history. If
> an account identifier was ever committed, pushing publishes every commit that
> contains it, regardless of what the current files say. Verify with:
>
> ```bash
> git grep -nI '<the value>' $(git rev-list --all)
> ```
>
> Nothing here is a credential, and no key was ever committed — but Render and
> Pinecone resource identifiers are account-scoped and worth keeping private.
> Deciding what to do is cheap now and impossible afterwards: history cannot be
> recalled once GitHub has it. With a short history, squashing to a single
> commit or re-initialising is cheaper than `git filter-repo` — and note that a
> squash only helps for values that are **no longer in the current tree**.

Once that is settled, confirm the prerequisites:

| | |
|---|---|
| Repository | pushed to GitHub, and the Render account can see it |
| `uv.lock` | at the repo root — Render auto-detects it and pins the build |
| `.python-version` | pins `3.13`. Services created after Feb 2026 default to 3.14, which CrewAI excludes and which **fails the build** |
| Credentials in hand | OpenRouter, Firecrawl, Pinecone, Cohere, and optionally a GitHub token |
| Pinecone index | exists, **768 dimensions**, cosine, serverless |
| `agentic-crew-ai-db` | already exists, created by hand outside any Blueprint. **This matters — see step 3.** |

Expect about **$13.30/month** fixed: $6.30 for the database, $7.00 for the API on
`starter`, $0 for the static site. Model tokens and tool calls are on top.

---

## 1. Push, and let CI go green first

`.github/workflows/ci.yml` runs the unit suite and the frontend build on every
push. Both are free and neither needs a credential. If CI is red, Render will
build the same broken tree — fix it before you spend money on a deploy slot.

---

## 2. Create the Blueprint

In the Render dashboard: **New → Blueprint**, select the repository, let it
detect `render.yaml` at the root.

Do **not** approve the apply yet. Render shows you a preview first, and the
preview is the whole point of this step.

---

## 3. ⚠️ Check the preview LINKS the database — do not let it create a second one

This is the step that costs real money if you get it wrong.

`agentic-crew-ai-db` was created by hand, outside any Blueprint. `render.yaml`
declares a `databases:` entry whose every field — `databaseName`, `user`, `plan`,
`region`, `diskSizeGB`, `postgresMajorVersion` — mirrors the live instance
exactly, precisely so that Render recognises it and adopts it.

**On the apply preview, find the database row and confirm it reads as a link to
the existing `agentic-crew-ai-db`, not as a new resource to be created.**

If the preview proposes **creating** a database:

- **Stop. Do not apply.** You are about to get a second `basic_256mb` instance
  billing $6.30/month alongside the first, with the API pointed at the empty new
  one while all your data sits in the old one.
- The cause is a field mismatch between `render.yaml` and the live instance.
  Compare, in this order: `postgresMajorVersion` (must be `"18"`, quoted — the
  live instance was upgraded from 17 and Render treats the major version as part
  of the resource definition), then `plan`, `region`, `databaseName`, `user`,
  `diskSizeGB`.
- Fix `render.yaml` to match the live instance, push, and re-check the preview.

Note that `ipAllowList` is deliberately absent from `render.yaml` — but not
for the reason this document used to give. It said the live database "already
has an allow list". Queried against the Render API on 2026-08-30, the live
`ipAllowList` is `[]`: **empty**. On Render that means no external connections
at all, and only same-region internal traffic reaches the database.

Omitting the key preserves that safe state. Two consequences follow, and both
bite silently:

1. `DATABASE_URL` must be the **Internal Database URL**. An external one is
   refused, and the failure shows up at `/readyz`, not at startup.
2. The API service must stay in `singapore`. Move it and the database becomes
   unreachable with nothing in the configuration to blame.

Only when the database row reads *link*, apply.

---

## 4. Enter the secrets

Render prompts once, at Blueprint creation, for every variable marked
`sync: false`. Those values are stored as dashboard secrets and are never
committed. There are five, all on the **API** service (`agentic-crew-ai-api`):

| Variable | Required? |
|---|---|
| `OPENROUTER_API_KEY` | **yes** — every model call and every embedding |
| `FIRECRAWL_API_KEY` | **yes** — market research and Brief Crew scraping |
| `PINECONE_API_KEY` | **yes** — the warm cache |
| `COHERE_API_KEY` | **yes** — stage-2 rerank |
| `GITHUB_TOKEN` | **optional** — leave blank to run unauthenticated. Present, it raises GitHub search from 8 to 24 req/min. No scopes are needed. |

The sixth `sync: false` variable, `VITE_API_URL`, is on the **frontend** service
and you cannot fill it in correctly yet. Leave it blank for now — step 6.

Everything else in `render.yaml` is a non-secret literal: `PYTHON_VERSION`,
`RUN_CONCURRENCY`, `PINECONE_INDEX_NAME`, the three `CREWAI_*` settings, and
`DATABASE_URL` which Render wires from the linked database automatically.

`OPENAI_API_KEY` is **not** used and must not be set. Startup asserts that every
model constant carries an `openrouter/` prefix and refuses to boot otherwise.

---

## 5. First boot — the API

The build runs `uv sync --frozen --extra service`. The `--extra service` is
mandatory: `fastapi`, `sqlalchemy` and `psycopg[binary]` live in
`[project.optional-dependencies].service`, and a bare `uv sync` omits all three.
It does pull `uvicorn` transitively, which makes the failure look like a runtime
bug rather than a missing dependency — `create_app` raises `ServiceDependencyError`
at import.

Watch for, in order:

1. **Python 3.13, not 3.14**, in the build log's first lines. 3.14 fails.
2. **The build completes** and does not resolve anything fresh — `--frozen`
   installs exactly what `uv.lock` pins.
3. **`GET /healthz` returns 200.** It is the configured `healthCheckPath` and
   answers with no credentials set.
4. **`GET /readyz` returns 200.** This is the one that exercises the database.

### The schema, on real PostgreSQL for the first time

There is no migration step. `PostgresFlowPersistence.init_db()` calls
`metadata.create_all()` at construction, so first boot creates `flow_states`,
`pending_feedback`, `runs`, `run_node_metrics`, `run_frames` and `run_gates`.

**This will be the first time that DDL has ever run against PostgreSQL.** Every
automated test uses SQLite. The persistence layer is dialect-agnostic and there
is no reason to expect trouble, but "no reason to expect trouble" is not the same
as "tested", so check rather than assume:

- **The service actually reached `readyz`.** A DDL failure surfaces here, not at
  `healthz` — `healthz` answers before the database is touched.
- **All six tables exist** with the expected columns. Connect with `psql` via the
  Render dashboard's connection string and run `\dt`, then `\d run_frames`.
- **Watch for type mismatches SQLite silently tolerates.** SQLite is dynamically
  typed and PostgreSQL is not; a column SQLite accepted may be rejected here.
  This is the single most likely failure mode.
- **Restart the service once** and confirm it comes up clean. `create_all()` is
  idempotent, but that claim has not been exercised on this dialect either.

The DDL sketched in `agents/07-deployment.md` (`runs` / `run_metrics` /
`run_sources`) is **design intent, not what ships.** Do not apply it. The
SQLAlchemy models own the schema.

### What is still untested after a green boot

Concurrency. Both `pending_feedback` and the gate reply use
`UPDATE ... WHERE ...` plus a `rowcount` compare-and-set. SQLite's single-writer
model cannot stress that, so it has never been exercised under contention. A
normal run will not exercise it either. To actually test it, have two processes
reply to the same gate and confirm exactly one wins and the other gets HTTP 409.

---

## 6. ⚠️ `VITE_API_URL` — a full origin, including the scheme

Once the API service exists and has a URL, set `VITE_API_URL` on the **frontend**
service (`agentic-crew-ai-web`) and redeploy it.

```
✅  https://agentic-crew-ai-api.onrender.com
❌  agentic-crew-ai-api.onrender.com            (no scheme)
❌  //agentic-crew-ai-api.onrender.com          (no scheme)
❌  https://agentic-crew-ai-api.onrender.com/   (trailing slash is stripped, but do not rely on it)
```

**Why this is not a nitpick.** `frontend/src/services/studioApi.ts` uses the value
two ways: as a prefix for `fetch`, and as the base of `new URL(...)` when building
the WebSocket URL. A scheme-less value resolves as a *relative path*, `/ws` never
connects, and the client concludes no backend is reachable.

**It then falls back to its scripted mock and renders a complete, fabricated
run** — nodes lighting up, evidence, a verdict, a report. Nothing errors. Nothing
is red. The page looks like a working deployment and every number on it is
invented. This is the worst failure mode in the system precisely because it is
silent, and a bare hostname is the easy way to cause it.

This is also why `render.yaml` cannot use `fromService … property: host` to wire
it automatically: that yields a bare hostname, which is exactly the broken case.
Hence `sync: false` and this manual step.

`VITE_API_URL` is a **Vite build-time** variable. It is baked into the bundle, so
changing it requires a **rebuild**, not a restart. Trigger a manual deploy of the
static site after you set it.

### Verify you are on the real backend, not the mock

After the redeploy, open the site and confirm:

- The browser devtools **Network** tab shows requests to your API origin, and a
  **WebSocket connection to `/ws` that stays open** (status 101).
- `GET https://<your-api>/api/workflows` returns JSON in the browser directly.
- Launch a run and confirm a row appears in the `runs` table in PostgreSQL. This
  is the unambiguous test: the mock cannot write to your database.

---

## 7. First real run

The first live end-to-end validator run has never happened. Treat it as an
experiment, not a smoke test.

- Enable traces first: `crewai traces enable`. Traces can include prompts, task
  inputs and outputs, tool arguments and results, and model responses — check
  what a trace contains before sharing its URL.
- Take one idea through **both human gates**. The gates are the part that
  exercises durable persistence, and resuming from a gate is what the whole
  recovery story rests on.
- **Inspect citation closure in the report** before believing the verdict: every
  URL in the final Markdown should trace back to a real tool result.
- Watch memory. `RUN_CONCURRENCY` is `1` because one run is roughly the ceiling
  on a 512 MB `starter` instance (~210 MB baseline). Raising it is how you get
  an OOM.

---

## Known operational edges

- **`maxShutdownDelaySeconds: 300`** is Render's ceiling, not a comfortable
  margin. On `SIGTERM` the lifespan calls `RunRegistry.close()`, which waits on an
  already-executing CrewAI step, and a full six-agent run can exceed five
  minutes. A redeploy mid-run can still be `SIGKILL`ed. Durable persistence plus
  resume is the mitigation — deploy when nothing is running.
- **Tracing from Render is ephemeral.** `CREWAI_TRACING_ENABLED=true` is set, but
  traces will not be attributed to your AMP org. The credential is an encrypted
  `tokens.enc` written by an interactive `crewai login`, it expires, and there is
  no env-var equivalent. **Never bake `tokens.enc` into an image.** PostgreSQL is
  the production record; AMP is a local/dev capability.
- **The `serve` console script is not the container entry point.** It honours
  `$PORT` but defaults `HOST` to `127.0.0.1`, which Render's proxy cannot reach.
  `render.yaml` sidesteps this by invoking uvicorn explicitly with
  `--host 0.0.0.0`; if you ever change the start command, set `HOST=0.0.0.0`.
- **`--factory` is mandatory** in the start command. The ASGI entry point is
  `create_app`, a factory, not a module-level `app`.
- **`--no-sync` is mandatory** in the start command. Without it `uv run` re-syncs
  at boot, computes the default dependency set, and **removes the `service` extra
  the build just installed.**
- **Region is immutable after creation.** `singapore` matches both the Postgres
  instance and the Pinecone index; the static site is deliberately unpinned
  because it is served from a global CDN.
- **The Docker image has never been built.** `Dockerfile` and `.dockerignore`
  exist and target the API only, but no Docker daemon was available where they
  were written. The Blueprint path above does not use them.

---

## Rollback

Render keeps previous deploys. If a deploy is bad, roll back the service from the
dashboard rather than pushing a revert commit — it is faster and it does not
rebuild.

The database is not rolled back with it. If a schema change is ever involved,
take a backup first; `basic_256mb` includes them, but confirm one exists before
you need it.
