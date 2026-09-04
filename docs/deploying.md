# Deploying to Render

What to do after the repository is pushed. Everything here is a manual step —
[`render.yaml`](../render.yaml) is a manifest, and writing a manifest is not the
same as applying it.

Source of truth for the resource decisions is
[`agents/07-deployment.md`](../agents/07-deployment.md). This file is the ordered
procedure; that one is the reasoning.

> **Read [`gotchas-and-insights.md`](gotchas-and-insights.md) entries 1-8 before
> you start.** They are the deployment traps that each cost a real debugging
> cycle and none of which is discoverable from the code or from this procedure:
> the empty `ipAllowList` and what it forces about regions, `VITE_API_URL`
> failing *silently* into a fabricated UI, Render snapshotting a deploy's
> environment at creation rather than at start, and the Public Suffix List
> making cross-subdomain cookies impossible on `onrender.com`.
>
> Two of them are restated below as steps, because you need them at the moment
> they apply. The rest are not.

> **Neither the flow builder nor the gauntlet build changed the build inputs,
> and that is measured rather than assumed.** Re-run 2026-09-04 at `bc12642`,
> over everything from the last commit before the builder existed:
>
> ```bash
> git diff --stat 4d70cbf..HEAD -- render.yaml pyproject.toml uv.lock \
>   frontend/package.json frontend/package-lock.json \
>   .github/workflows/ci.yml Dockerfile
> # .github/workflows/ci.yml | 54 ++++++++++++++++++++++++++++++++++++++++++++++
> # 1 file changed, 54 insertions(+)
> ```
>
> One file, and it is the `postgres` CI job. **No new Python dependency, no new
> npm dependency, no new build step, and no environment variable added to either
> service by any of it** — the MCP, tools, skills and model-registry work is all
> built on packages `uv.lock` already pinned. Steps 1-3, 6 and 7 below are
> unchanged; **step 4 is not**, because the code now demands a secret the
> manifest never carried.
>
> What these changes *do* touch is the **database** — thirteen tables now, and a
> third additive column on one that has already shipped — and what happens at
> **boot**: a published user graph lives in the database and its registration
> does not, so every restart has to put it back. Both are in step 5.

---

## Go-live checklist

**What must be true before a merge to `main`, in the order it must be true.**
Both Render services carry `autoDeploy: yes`, so **the merge *is* the deploy** —
there is no separate "press deploy" moment at which to notice something. Every
line has the command that checks it and a verdict measured on **2026-09-04 at
`gauntlet/plans` = `bc12642`**, in the integration worktree, on Windows.

**Five lines are NOT READY, five more are unverified, and two of the five red
ones would break the deploy outright** — row 3 (the studio never builds) and
row 8 (the API never starts). Four are green and two are operator judgement. An
honest checklist that names them is worth more than a green one that does not;
re-run each command rather than trusting the verdict beside it.

> The working tree carried **uncommitted edits from three concurrent build
> agents** when these were run. Where that changes the reading, the line says
> so — and it is the reason the frontend rows are red while the committed branch
> is not.

### Gate 1 — the tree builds and passes

| # | Must be true | Command | 2026-09-04 |
|---|---|---|---|
| 1 | Python suite green | `PYTHONPATH=<worktree>/src python -m unittest discover -s tests -t .` | ✅ **READY** — `Ran 2023 tests in 127.201s / OK (skipped=6)` |
| 2 | Frontend unit suite green | `cd frontend && npm test` | ❌ **NOT READY** — `1400 tests, 37 failed` in `builderDefaults.spec.ts` (33), `builderImport.spec.ts` (2), `versionBrowser.spec.ts` (2). Caused by **uncommitted** work in progress: `git show HEAD:frontend/src/types/builder.ts` contains no `max_prompt_chars` / `AuthoredAgentConfig`, the working copy contains seven such references |
| 3 | Type-check and production build green | `cd frontend && npx vue-tsc -b --force` | ❌ **NOT READY — this alone fails the studio deploy.** `exit 2`, 11 errors, same cause as row 2. `npm run build` is `vue-tsc -b && vite build && tsc -p tsconfig.server.json`, so the build stops at the first step and Render's studio service never produces a bundle |
| 4 | E2E green against the free backend | backend on 8099 (`SYNTHETIC=1`, `SYNTHETIC_BRANCH_DELAY_SECONDS=5`, `CREDENTIALS_MASTER_KEY`, `PYTHONPATH`), then `cd frontend && npx playwright test` | ⚠️ **NOT RUN this pass.** `npx playwright test --list` answers **69 tests in 8 files**; `--list --grep-invert @launch` answers 60, so **9 are `@launch`**. A list is not a run |
| 5 | Two writers on PostgreSQL 18 | `docker start pg18-test`; `TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:5433/postgres python -m unittest tests.pg.test_two_writers -v` | ✅ **READY** — `Ran 5 tests in 23.317s / OK` against `PostgreSQL 18.6 (Debian 18.6-1.pgdg13+2)`. All five compare-and-set paths, two processes each |
| 6 | CI green on the branch | `gh run list --branch <branch> --limit 5` | ⚠️ **NOT CHECKED** — this pass made no network call. Note the `postgres` job is `if: github.ref == 'refs/heads/main'`, so it has **never run**; the merge to `main` is its first execution |
| 7 | Both manifests parse | `python -c "import yaml; [yaml.safe_load(open(f, encoding='utf-8')) for f in ('render.yaml', '.github/workflows/ci.yml')]"` | ✅ **READY** — also a CI step |

### Gate 2 — the deployment is configured

| # | Must be true | Command | 2026-09-04 |
|---|---|---|---|
| 8 | `CREDENTIALS_MASTER_KEY` is set on the **API** service in the Render dashboard | dashboard → `agentic-crew-ai-api` → Environment | ❌ **NOT READY.** `render.yaml` now declares it `sync: false`, and an already-applied Blueprint does **not** re-prompt. Without it the API **does not start** — see step 4. Reproduce the failure locally before you believe this line |
| 9 | The three URL literals match the URLs Render proposes | step 3a, then read the three `value:` lines: `grep -n -A1 'key: CORS_ALLOW_ORIGINS' render.yaml` and the same for the other two keys | ⚠️ **NOT VERIFIABLE from a checkout.** Item 16. Check on the apply preview |
| 10 | No provisional flag is set anywhere | `grep -nE 'BUILDER_CODE_INTERPRETER|MCP_STDIO|MCP_ALLOWED|PLATFORM_FIRECRAWL' render.yaml` | ✅ **READY** — no `key:` line for any of them, and no dashboard override should exist either. Decisions 3, 7, 8 and 9 are provisional and stay off |
| 11 | `MAX_RUN_COST_USD` is a value somebody chose | dashboard, plus CLAUDE.md Next Sequence step 2 | ⚠️ **NOT READY as a decision.** Unset means the $10 default is *on*, which is safe; nobody has chosen it deliberately for a public deployment |
| 12 | Nothing is mid-run | dashboard, or `GET /api/runs/...` | operator check. `maxShutdownDelaySeconds: 300` waits on an executing CrewAI step and a full run can exceed five minutes; a redeploy can still `SIGKILL` mid-flight |
| 13 | Every builder graph an author cares about is **published**, not mid-edit | sign in, open `#/build` | operator check. Editing a published graph makes it a draft, and the boot sweep only re-registers rows whose status is `published` — so a graph left mid-edit is registered now and gone after this deploy |

### Gate 3 — the things that are not code

| # | Must be true | Check | 2026-09-04 |
|---|---|---|---|
| 14 | The repository has a `LICENSE` | `ls LICENSE*` | ❌ **NOT READY** — `No such file or directory`, and `git ls-files` finds none. The repo is **public**, which means all rights reserved. `pyproject.toml:7` already carries the note saying so. This is remaining-work item 17 and MISSION §12 item 4, and it is a decision only the owner can make |
| 15 | The platform Firecrawl cap exists before decision 9 is confirmed | `grep -rn BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP --include=*.py src` | ❌ **NOT READY** — the knob has no consumer. Do not ask the owner to confirm decision 9 until it does; see step 4 |
| 16 | Someone has decided what a *published user graph* may cost | CLAUDE.md Next Sequence step 2 | ⚠️ **OPEN.** A second thing on this deployment can now spend money and none of its three levers has been chosen deliberately |

### What this checklist deliberately does not claim

- **It does not say the deployed service is healthy.** Every live figure in
  `CLAUDE.md`'s *Deployment — Live* table was probed on 2026-08-30 and has not
  been re-probed since; this pass made no network call of any kind.
- **It does not cover the paid acceptance run.** That is remaining-work item 1,
  it costs money, and no automated pass may authorise it.
- **A green Gate 1 proves the plumbing, not the agents.** The E2E suite runs
  against a `SYNTHETIC=1` backend; point it at a paid origin with `E2E_BASE_URL`
  and nine of its 69 tests spend money.

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
`starter`, and $0 for `agentic-crew-ai-studio`, which `render.yaml` puts on
`free`. Model tokens and tool calls are on top, and the only thing bounding a
single run of them is `MAX_RUN_COST_USD` — see
[Known operational edges](#known-operational-edges).

The studio is a **Node web service**, not a static site. It was one until Better
Auth arrived, which needs a runtime a CDN cannot give it; `render.yaml` carries
the two consequences (one origin, and `region: singapore` is now mandatory) at
the point they bind.

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

Only when the database row reads *link*, apply — after step 3a.

---

## 3a. ⚠️ Check the three URL literals against the URLs Render proposes

Two URLs are written into `render.yaml` three times, and **neither exists until
this apply creates the services**:

| Key | Service | Value |
|---|---|---|
| `CORS_ALLOW_ORIGINS` | api | `https://agentic-crew-ai-studio.onrender.com` |
| `AUTH_BASE_URL` | api | `https://agentic-crew-ai-studio.onrender.com` |
| `VITE_API_URL` | studio | `https://agentic-crew-ai-api.onrender.com` |

They are literals rather than `sync: false` on purpose: Render derives a
service's hostname from its `name`, and both names are declared in this same
file, so the values are **predictable**. `VITE_API_URL` was `sync: false` once,
the manual step was missed, and the live console shipped talking to itself.

Predictable is not guaranteed. **If either `name` is already taken in the
account, Render appends a suffix and all three literals are silently wrong.**
There is no manifest expression that fixes this — `fromService … property: host`
yields a bare hostname with no scheme, which is the exact broken case every one
of those three keys warns about. So it is a manual check, and this is the moment
it applies:

**On the apply preview, before applying, read the URLs Render proposes for
`agentic-crew-ai-api` and `agentic-crew-ai-studio`. If either differs from the
table above, edit all three keys, push, and re-preview.**

```bash
grep -nE 'CORS_ALLOW_ORIGINS|AUTH_BASE_URL|VITE_API_URL' -A1 render.yaml | grep value:
```

Do not apply and patch afterwards. Render **snapshots a deploy's environment
when the deploy is created** (deployment trap 3), and `VITE_API_URL` is inlined
by Vite at **build** time — so a later edit needs a fresh deploy of the studio,
not a restart.

Each of the three fails differently and none of them fails loudly:

- wrong `CORS_ALLOW_ORIGINS` → the browser drops every response; reads as
  missing middleware.
- wrong `AUTH_BASE_URL` → JWKS location, `iss` and `aud` are all wrong at once;
  reads as a credential problem.
- wrong `VITE_API_URL` → the console falls back to its scripted mock and renders
  a complete, fabricated run with nothing red on the page. This is the worst
  failure mode in the system.

This is CLAUDE.md remaining-work **item 16**. The item is not closed by writing
this section — it is downgraded from "a wrong value ships silently" to "a
checked value ships", which is as far as a manifest can take it.

---

## 4. Enter the secrets

Render prompts once, at Blueprint creation, for every variable marked
`sync: false`. Those values are stored as dashboard secrets and are never
committed. There are **ten**, split across the two services. Counted from the
manifest rather than from memory — measured 2026-09-04, and it was nine the day
before:

```bash
grep -n -B1 'sync: false' render.yaml | grep 'key:' | wc -l   # 10
```

Six on the **API** (`agentic-crew-ai-api`):

| Variable | Required? |
|---|---|
| `CREDENTIALS_MASTER_KEY` | **yes, and the service will not START without it.** See the box below |
| `OPENROUTER_API_KEY` | **yes** — every model call and every embedding |
| `FIRECRAWL_API_KEY` | **yes** — market research and Brief Crew scraping |
| `PINECONE_API_KEY` | **yes** — the warm cache |
| `COHERE_API_KEY` | **yes** — stage-2 rerank |
| `GITHUB_TOKEN` | **optional** — leave blank to run unauthenticated. Present, it raises GitHub search from 8 to 24 req/min. No scopes are needed. |

> ### ⚠️ `CREDENTIALS_MASTER_KEY` is a boot requirement, not a feature flag
>
> This is the one item on this page that turns a green-looking deploy into a
> service that never comes up, and the previous revision of this file did not
> mention it at all.
>
> `_assert_credential_vault_startup_safety()` runs **inside `create_app`**
> (`src/brief_crew/service/app.py`, called at `:673`, before a route is
> mounted) and raises when `AUTH_BASE_URL` is set and this key is empty. The
> reasoning is the one `VALIDATOR_REQUIRE_AUTH` already uses: a deployment that
> can sign people in and has nowhere to keep their API keys is misconfigured,
> and the half-configured state is the quiet failure — so it fails loud
> instead. `render.yaml` sets `AUTH_BASE_URL`, so on this deployment the key is
> mandatory.
>
> **Measured, not reasoned.** On 2026-09-04 at `bc12642`, building the app with
> exactly this environment:
>
> ```text
> AUTH_BASE_URL=https://agentic-crew-ai-studio.onrender.com CREDENTIALS_MASTER_KEY= >   python -c "from brief_crew.service.app import create_app; create_app()"
>
> RuntimeError: AUTH_BASE_URL is set but CREDENTIALS_MASTER_KEY is empty; people
> can sign in and the credential vault has no key to keep theirs with. Mint one
> with python -c "import base64, secrets;
> print(base64.b64encode(secrets.token_bytes(32)).decode())" and set it
> ```
>
> The same command with a valid key returns a `FastAPI` instance. Mint one,
> once:
>
> ```bash
> python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
> ```
>
> **Do not rotate it casually.** Every stored credential is encrypted under it,
> and `credentials.py` *detects* a changed key and refuses rather than silently
> re-wrapping — `CREDENTIALS_MASTER_KEY changed without a re-encrypt pass`.
>
> **If the Blueprint is already applied**, Render prompted for `sync: false`
> values at creation and will not prompt again: set this in the dashboard
> **before** the next deploy. A deploy that reaches this code without it fails
> its health check and rolls back. That is deployment trap 3 wearing a new hat
> — Render snapshots a deploy's environment when the deploy is *created*.

Four on the **studio** (`agentic-crew-ai-studio`), all for sign-in — the exact
values and where each comes from are in [`google-oauth.md`](google-oauth.md):

| Variable | Required? |
|---|---|
| `BETTER_AUTH_SECRET` | **yes** — `openssl rand -base64 32`, once. Rotating it invalidates every session and every issued JWT |
| `BETTER_AUTH_URL` | **yes** — this service's own origin, scheme included. It must equal `AUTH_BASE_URL` on the API |
| `GOOGLE_CLIENT_ID` | **yes** |
| `GOOGLE_CLIENT_SECRET` | **yes** |

**`VITE_API_URL` is no longer among them.** It was `sync: false` and the manual
step was missed on the live studio, which shipped a bundle whose API base was
the empty string — every call resolved against the studio's own origin, hit the
SPA fallback, and came back `200 text/html`. `render.yaml` now hardcodes it, for
the same reason `AUTH_BASE_URL` is hardcoded: the API's URL is knowable when the
manifest is written. Step 6 is now a *verification*, not a data-entry step.

Everything else in `render.yaml` is a non-secret literal: `PYTHON_VERSION`,
`RUN_CONCURRENCY`, `PINECONE_INDEX_NAME`, the three `CREWAI_*` settings,
`CORS_ALLOW_ORIGINS`, `AUTH_BASE_URL`, `NODE_ENV`, `NODE_VERSION`,
`VITE_API_URL`, and `DATABASE_URL` on both services, which Render wires from the
linked database automatically.

### What `render.yaml` deliberately does NOT set

**Fourteen** knobs that govern what a run may cost, what the builder may do,
what a stdio process may be, and how long data is kept are **absent from the
manifest**, so production runs on their code defaults. That is the right answer
for thirteen of them and a decision the owner still owes on one. Checked
directly:

```bash
grep -nE 'MAX_RUN_COST_USD|BUILDER_|MCP_|SKILLS_ROOT|RETENTION' render.yaml
# comments only, no `key:` line for any of them
```

The full inventory of environment knobs — **forty-nine**, regenerated
2026-09-04 — with the command that regenerates it, is
[`tech-stack.md` §6](tech-stack.md). Do not maintain a second copy there or
here; what this table owns is the *production decision*, which that file
deliberately does not.

#### Cost and lifecycle

| Knob | Default | Set it to | Why |
|---|---|---|---|
| `MAX_RUN_COST_USD` | `10.0` | **leave unset for now**, and read the note below | Every run carries a ~$10 ceiling enforced at the next CrewAI step boundary. `0` disables it; **unset does not**. It has never fired on a paid run, and it is arithmetic over a local `PRICES` table rather than an invoice |
| `BUILDER_ALLOW_GATELESS_GRAPHS` | `False` | **leave unset** | An *anonymous* caller cannot launch a user graph that bills before any human gate — 403. Irrelevant while auth is on, because `user` is then always truthy, which is exactly why leaving it off costs nothing and turning it on would be a hole waiting for the day auth is disabled |
| `BUILDER_REHYDRATE_PUBLISHED` | `True` | **leave unset** | Published builder graphs are re-registered at every boot. Turning it off boots with *no* user graph registered at all; it is a break-glass lever, not a test lever. See step 5 |
| `VALIDATOR_RUN_RETENTION_DAYS` | `0` | **leave unset until decision 23 is answered**, then set it explicitly | `0` means keep every terminal run, its frames, its metrics and its gates **forever**. The database is `basic_256mb` with a 1 GB disk and one paid run wrote 102 frames, so this is slow growth rather than a leak — but it is unbounded in time and nothing warns. Documents, versions, credentials, skills and tools are never purged by it either way |

> **`MAX_RUN_COST_USD` is the runaway brake and unset means ON.** Only a
> deliberate `MAX_RUN_COST_USD=0` disables it. It is not a budget — against the
> measured clean run it is roughly 55x — and it does not bound the cent: it
> stops at the next CrewAI `PRE_STEP` boundary, so expect to overshoot by about
> one escalation call, and it is blind to embeddings, rerank and Firecrawl,
> which raise no LLM event. Choosing a deliberate value for a public deployment
> is step 2 of CLAUDE.md's Recommended Next Sequence and **it is still open.**

#### The four provisional rulings — OFF, and they stay off until the owner says otherwise

`PLANS.md` marks decisions 3, 7, 8 and 9 **provisional — owner to confirm**,
because each spends the owner's money or opens a surface. Every one is off in
the code and unset in the manifest. **Do not set any of them as part of a
deploy.** Each row says what turning it on would actually do.

| Knob | Default | Set it to | Why |
|---|---|---|---|
| `BUILDER_CODE_INTERPRETER_ENABLED` | `False` | **leave unset — decision 3, provisional** | It gives an agent node CrewAI's code interpreter, which runs **author-written Python in an E2B sandbox** on a BYO E2B key. A canvas is a place strangers type things; this makes one of those things a program. It is also on a deprecation path — CrewAI 1.15.18 marks `allow_code_execution` and `code_execution_mode` `Field(deprecated=True)` — so the surface it opens is one that is going away |
| `MCP_STDIO_ENABLED` | `False` | **leave unset — decision 7, provisional** | This is the gate that matters. A stdio MCP server means **an author's saved document names a process to run on the server**, which is precisely what the compiler's closed `BUILDER_ACTION_REFS` set exists to prevent: everywhere else author data reaches a compiler-owned entrypoint as a *value*, never as a name. Remote `https://` servers are the production answer and they already work |
| `MCP_ALLOWED_COMMANDS` | empty | **leave unset — the two gates stack** | The allow-list a stdio command must be on *once the flag above is lifted*. Empty means the flag alone opens nothing, and that is the design: two deliberate acts, not one. Lifting the flag and leaving this empty is a safe intermediate state; setting this while the flag is off does nothing at all. If stdio is ever approved, name exact commands (`npx,uvx`) and never a shell |
| `MCP_ALLOWED_ENV_VARS` | empty | **leave unset** | The environment keys a stdio server may be handed. A key outside the set is **refused rather than dropped**, so an author is told rather than handed a server that silently has no credential. Same stacking rule |
| `BUILDER_PLATFORM_FIRECRAWL_DEFAULT` | `False` | **leave unset — decision 9, provisional, and read the warning** | It makes the platform's own Firecrawl key every author's default. Off, the three Firecrawl tool entries and `research_market_landscape` require the author's own `firecrawl` credential and say so on the card |
| `BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` | `50` | **leave unset — it does nothing** | See the warning |

> ### ⚠️ The platform Firecrawl cap is documented and **nothing decrements it**
>
> Decision 9 is conditioned on "a daily cap and per-user override". The
> per-user override exists. **The cap does not.** Measured 2026-09-04 at
> `bc12642`:
>
> ```bash
> grep -rn 'BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP' --include=*.py --include=*.ts \
>   src frontend/src tests
> # src/brief_crew/config.py:3141  - its own definition, and nothing else
>
> grep -rn 'BUILDER_PLATFORM_FIRECRAWL_DEFAULT' --include=*.py src
> # src/brief_crew/config.py:3137        - its definition
> # src/brief_crew/builder/tools.py:576  - credential_optional=...
> ```
>
> So the flag has an effect and its cap has no consumer: no counter, no store,
> no reset. **Turning `BUILDER_PLATFORM_FIRECRAWL_DEFAULT` on today is an
> uncapped spend of the owner's Firecrawl quota by anybody who can sign in**,
> not the capped one the ruling describes. Say that to the owner before asking
> them to confirm decision 9; the honest sequence is to build the counter
> first, then ask.

#### Storage and local addresses

| Knob | Default | Set it to | Why |
|---|---|---|---|
| `MCP_ALLOW_INSECURE_LOCAL` | `False` | **leave unset** | It admits `http://127.0.0.1` and `http://localhost` as remote MCP servers, for local development and the E2E loopback fixture. Inside a Render container that reaches nothing useful and relaxes the one rule (`https://` required, every other private/loopback/link-local address refused) that stops a saved document being an SSRF probe |
| `SKILLS_ROOT` | `data/skills` | **leave unset**, and know what it depends on | The four built-in skill packs are **committed files** under `data/skills/builtin/*/SKILL.md`, and the default is resolved **relative to the process's working directory**. On Render that is the repository root and it works. `load_builtins()` does `if not path.exists(): continue`, so pointing this at a mounted disk that does not contain the built-ins yields **zero** built-in skills with no error anywhere. If you ever move it, copy `data/skills/builtin/` alongside. User packs are safe either way: the database is the durable copy and disk is a materialisation cache that rewrites on content mismatch |

`VALIDATOR_ALLOW_AUTO_GATES` is absent for the same class of reason and
`render.yaml` explains it at the point it is missing.

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

### The schema — thirteen tables now, and three additive columns

There is no migration step. `PostgresFlowPersistence.init_db()` calls
`metadata.create_all()` at construction, then `_add_missing_columns()`. There are
**thirteen** tables now, not eight and not six. Regenerate the list rather than
trusting this one — it has been wrong at every previous revision of this file:

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -c "from brief_crew.service.persistence import metadata; ts=sorted(metadata.tables); print(len(ts)); print(ts)"
```

Measured 2026-09-04 at `bc12642` — **13**: `builder_document_versions`,
`builder_documents`, `builder_test_inputs`, `flow_states`, `mcp_servers`,
`pending_feedback`, `run_frames`, `run_gates`, `run_node_metrics`, `runs`,
`user_credentials`, `user_skills`, `user_tools`.

The five new ones are the gauntlet tables (contract C10): `user_credentials`,
`user_tools`, `mcp_servers`, `user_skills` and `builder_test_inputs`. **None has
ever shipped**, so `create_all()` creates each one with its indexes and
constraints intact on the first boot after this deploy, and no migration is
needed — the easy case, for the same reason the two builder tables were.

**`_ADDITIVE_COLUMNS` carries three entries now, not one**, and the third is the
one that matters this deploy:

```text
("runs",                        "user_id", "VARCHAR(128)")   # shipped, done
("runs",                        "mode",    "VARCHAR(16)")    # NULL reads as `run`
("builder_document_versions",   "source",  "VARCHAR(64)")    # NULL reads as `stored`
```

`builder_document_versions` **shipped on 2026-09-02**, so `source` is the second
column in this project's history to reach an already-deployed table by this
path, and `create_all()` would never have added it. Nothing is backfilled and
nothing needs to be: both new columns are nullable and their NULL has a
documented reading.

**The six original tables have run against PostgreSQL 18 in production**: the
deployed API answered `/readyz` with `"backend":"postgresql"` — probed
2026-08-30, recorded in [`../CLAUDE.md`](../CLAUDE.md), **not re-probed for this
revision**. The **two builder tables have not**, and every automated test in this
repo is still SQLite — `grep -rl postgres tests/` finds nothing, verified
2026-09-02 at `b4ef654`. So the paragraph below is no longer a
warning about the whole schema; it is a warning about the two new tables.

**A new table is the easy case, and it is worth being precise about why.**
`create_all()` is create-if-absent *per table*: it does nothing at all to a table
that already exists, but it creates one that does not. `builder_documents` and
`builder_document_versions` are therefore created on an already-deployed
database on the first boot after this deploy, with their columns and
`ix_builder_documents_user_updated` intact, and no migration is needed. That is
the opposite of the `user_id` case, which was a **column** on a table that had
already shipped and which `create_all()` will never add — see
[`gotchas-and-insights.md`](gotchas-and-insights.md).

> **The forward hazard, for whoever adds the next column — and it has NOT
> moved with the table count.** The index-ensuring loop beneath
> `_ADDITIVE_COLUMNS` still iterates **`runs.indexes` and nothing else**
> (`persistence.py`, `for index in runs.indexes:`). So an additive column is
> handled for any table, but an **index** on a newly added column of any table
> other than `runs` is created on a fresh database and silently absent on this
> deployed one. A column with no explicit `_ADDITIVE_COLUMNS` entry fails at the
> first INSERT rather than at startup; a missing index costs a slow query and
> never a wrong answer, which is why the loop logs and continues rather than
> refusing to start. Anything needing a backfill, a NOT NULL, a rename or a drop
> is the point at which a real migration tool has become cheaper than that list.

Check rather than assume:

- **The service actually reached `readyz`.** A DDL failure surfaces here, not at
  `healthz` — `healthz` answers before the database is touched.
- **All thirteen tables exist** with the expected columns. Connect with `psql`
  via the Render dashboard's connection string and run `\dt`, then
  `\d builder_document_versions` — and confirm it has a `source` column, which
  is the one thing on this deploy that `create_all()` could not have done.
- **The service started at all.** Since plan 01 the API refuses to boot when
  `AUTH_BASE_URL` is set and `CREDENTIALS_MASTER_KEY` is not, so a deploy that
  never reaches `healthz` and shows `RuntimeError: AUTH_BASE_URL is set but
  CREDENTIALS_MASTER_KEY is empty` in the log is a missing dashboard secret and
  not a broken build. Step 4 has the whole entry.
- **Watch for type mismatches SQLite silently tolerates.** SQLite is dynamically
  typed and PostgreSQL is not; a column SQLite accepted may be rejected here.
  This remains the single most likely failure mode, and the builder gives it a
  new target: `_json_type()` resolves to plain `JSON` on SQLite and **`JSONB` on
  PostgreSQL**, so `builder_document_versions.document` — the whole saved graph —
  is stored under a type no test has ever exercised.
- **Restart the service once** and confirm it comes up clean. `create_all()` is
  idempotent, and on this deployment it has now demonstrated that for the six
  original tables; the two builder tables get their first idempotent second pass
  on that restart.

The DDL sketched in `agents/07-deployment.md` (`runs` / `run_metrics` /
`run_sources`) is **design intent, not what ships.** Do not apply it. The
SQLAlchemy models own the schema.

### ⚠️ Every deploy unpublishes every user graph, unless the boot sweep runs

This is the one piece of builder behaviour a deployer has to know about, and it
exists because of a fact this file already states elsewhere: both services carry
`autoDeploy: yes`, so **every push to `main` restarts them.**

Publishing a builder graph writes to six places and all six are *process-local*
module state. (Six is the count for the *request*. `register_builder_workflow`
itself writes five — the sixth, this application's own runtime dict, is written
by `service/builder_api.py::_register_runtime` in the same request, because
`service/graph.py` holds no registry instance. `config.py:1920` enumerates all
six by name. Other files say five when they are counting the function, and that
is the same event under a narrower scope.) The document that caused those writes is in the database. Before
the sweep existed, the two disagreed after every restart in the worst possible
direction: `builder_documents.status` still said `published`, the author's canvas
still said `published`, and `POST /api/sessions/{id}/runs` answered **404** for a
workflow they had published an hour earlier.

`rehydrate_published_workflows` runs inside `create_app`, after the registry
exists and **before any request is served**, so no client can observe a window in
which a published graph is unregistered. `BUILDER_REHYDRATE_PUBLISHED` defaults
to `True` and `render.yaml` does not set it, so this is on in production.

**What happens when a stored graph no longer compiles: it is skipped, and the
boot continues.** That is deliberate. `MAX_BILLABLE_NODES`, `MAX_ESCALATION_NODES`
and `MAX_CYCLES` all carry measured justifications and are all expected to move,
and a graph published under a laxer set must not be able to stop the process
booting. The author gets one graph that is no longer launchable, which is honest;
everybody else gets a service. The sweep raises nothing at all — a store that
refuses is a log line too.

**So read the log after a deploy.** It is the only place this surfaces:
`/readyz` says nothing about the builder, and `GET /api/workflows` deliberately
still returns only the two built-in literals, so a rehydrated graph will never
appear there. Grep the deploy log for:

| Log line | Level | Means |
|---|---|---|
| `rehydrated N published builder graph(s): …` | INFO | the ids that are launchable again |
| `builder graph <id> no longer compiles and was not re-registered: …` | WARNING | one graph is down, with the compiler's own sentence |
| `N published builder graph(s) could not be restored and are not launchable until they are edited and republished: …` | WARNING | the roll-up of the above |
| `builder rehydration stopped: the document store refused mid-sweep` | ERROR | graphs behind that point are **not** restored — this is the store failing, not a bad document |

Then confirm from the outside: sign in, open `#/build`, and check the gallery
still shows each graph as published. `GET /api/builder/workflows` is the API
equivalent and is owner-scoped, so it answers for the signed-in caller only.

Three edges worth knowing before you go looking for a bug that is not there:

- **Editing a published graph makes it a draft again.** The live process keeps
  running the version that was published — that is the version whose budget was
  priced and whose ETag is in flight — but the sweep only reads rows whose status
  is `published`. So a graph left mid-edit is registered *now* and gone after the
  next deploy. Republish before you push.
- **The sweep reads at most 200 published documents** (`MAX_LIST_LIMIT` in
  `builder/store.py`, a literal with no environment override). The 201st never
  comes back, and nothing says so.
- **A graph published before the `crew_id` fix will not return.** A crew whose
  factory is not zero-arg constructible used to pass every structural check,
  publish cleanly, and then raise `TypeError` on the first *paid* run — after the
  scoper and all three research branches had already billed. `library_problems`
  now refuses it, and rehydration is one of the doors that refusal is closed at,
  so such a row is skipped here rather than restored into a landmine.

`BUILDER_REHYDRATE_PUBLISHED=false` exists for exactly one situation: a graph
that compiles and then wedges or bankrupts this deployment. It is a deploy-time
flip that boots with **no user graph registered at all**, which is a blunter
instrument than it sounds — it is not a per-graph switch, and it is not a test
lever.

### What is still untested after a green boot

Concurrency, and there is more of it than there was. `pending_feedback`, the gate
reply, the `reopen_gate` rollback, the orphan-run sweep, and now the builder's
document store all use `UPDATE ... WHERE ...` plus a `rowcount` compare-and-set.
SQLite's single-writer model cannot stress any of them, so none has ever been
exercised under contention. A normal run will not exercise them either.

Two things to actually test, both needing two processes:

- Have two clients reply to the same gate; confirm exactly one wins and the other
  gets HTTP **409**.
- Have two browsers save the same builder document from the same version;
  confirm two version rows are written, one head pointer moves, and the loser
  gets HTTP **409** rather than a silently lost edit.

---

## 6. ⚠️ `VITE_API_URL` — a full origin, including the scheme

`render.yaml` now **hardcodes** this on `agentic-crew-ai-studio`:

```yaml
- key: VITE_API_URL
  value: "https://agentic-crew-ai-api.onrender.com"
```

So there is nothing to type here any more — but there is something to *check*,
because the manual step this replaced was missed once on the live site and the
failure is silent. If your API service has a different name, this value and
`AUTH_BASE_URL` move together.

The form is the whole point:

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
Hence a hardcoded literal.

**An empty value fails the same way, and that is what actually happened.** It was
`sync: false` — "fill this in once the API's URL is known" — and on the live
studio it was never filled in. Vite *inlines* the value at build time, so an
empty one ships a bundle whose base URL is `''`: every API call resolves against
the studio's own origin, hits the SPA history fallback, and comes back
`200 text/html`. Measured on the deployed site on 2026-09-01 and recorded in
`render.yaml`'s own comment — `GET
https://agentic-crew-ai-studio.onrender.com/api/workflows` → 200 HTML, and the
console fell back to its scripted demo. Not re-probed for this revision.

`VITE_API_URL` is a **Vite build-time** variable. It is baked into the bundle, so
changing it requires a **rebuild**, not a restart. If you ever edit it, trigger a
manual deploy of the studio service — a restart will keep serving the old bundle.

### Verify you are on the real backend, not the mock

After the deploy, open the site and confirm:

- The browser devtools **Network** tab shows requests to your API origin, and a
  **WebSocket connection to `/ws` that stays open** (status 101).
- `GET https://<your-api>/api/workflows` returns JSON in the browser directly.
- Launch a run and confirm a row appears in the `runs` table in PostgreSQL. This
  is the unambiguous test: the mock cannot write to your database.
- `GET https://<your-api>/api/builder/vocabulary` returns JSON. It is the
  cheapest probe of the builder half: no document, no run, and deliberately **no
  auth** — it describes this build rather than anybody's data — so it works from
  a plain browser tab or `curl`. Then open `#/build` and confirm the palette is
  populated; an empty palette against a working studio is the wrong origin, not
  a broken canvas.

---

## 7. First real run

**One paid end-to-end validator run has happened** and it found three defects no
test had, all since fixed and none re-exercised live — the ledger is in
[`../CLAUDE.md`](../CLAUDE.md), not here. Treat the next one as an experiment,
not a smoke test.

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
- **A user-drawn graph is the same experiment again, with a different bound.**
  A published builder graph runs through the same CrewAI engine, the same
  durable gates and the same cancellation as the validator, so nothing here
  changes — but what stops it is arithmetic rather than a human: the static
  estimate refused it at publish time, and `MAX_RUN_COST_USD` stops it at a step
  boundary. Read that ceiling's three structural limits in `config.py` before
  relying on it — it enforces an estimate rather than an invoice, it cannot stop
  a call already in flight, and it is blind to embeddings, rerank and Firecrawl.

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
- **Region is immutable after creation, and the studio is no longer exempt.**
  `singapore` matches the Postgres instance and the Pinecone index. The studio
  service used to have deliberately no region at all, because a static site is
  served from a global CDN; it is a Node service now, it writes Better Auth
  sessions to that database, and the database's `ipAllowList` is empty — so
  `region: singapore` on it is load-bearing. Move it and logins break with
  nothing in the configuration to blame.
- **The studio is on `free`, so the first visitor of the day waits on the
  sign-in page.** A free service spins down after inactivity, and a cold start
  lands in the worst possible place: before anyone can sign in, and before the
  API's first JWKS fetch. `starter` is the fix and the code is identical either
  way.
- **`MAX_RUN_COST_USD` is the runaway brake, and it is unset in `render.yaml`,
  which means it is on.** Unset gives the $10 default; only a deliberate
  `MAX_RUN_COST_USD=0` disables it. It is not a budget — against the measured
  clean run it is roughly 55x — and it does not bound the cent: it stops at the
  next CrewAI `PRE_STEP` boundary, so expect to overshoot by about one
  escalation call. `config.py` carries the derivation and the three things it
  structurally cannot do.
- **`maxShutdownDelaySeconds` has a second consumer now.** A builder graph runs
  on the same executor as the validator and is waited on the same way, so a
  deploy during someone's user-drawn run has the same five-minute ceiling and the
  same answer: deploy when nothing is running.
- **A missing `CREDENTIALS_MASTER_KEY` is a dead service, not a degraded one.**
  It is the only environment variable on this deployment whose absence stops the
  process rather than a feature. It is `sync: false`, and Render prompts for
  `sync: false` values only at Blueprint **creation** — so on an
  already-applied Blueprint it must be entered in the dashboard by hand before
  the next deploy. Reproduce the failure locally in ten seconds before believing
  it is set; step 4 has the command.
- **The platform Firecrawl daily cap has no consumer.** If anyone ever sets
  `BUILDER_PLATFORM_FIRECRAWL_DEFAULT=true`, the spend is uncapped in practice
  whatever `BUILDER_PLATFORM_FIRECRAWL_DAILY_CAP` says. Measured 2026-09-04; see
  step 4.
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

**A rollback of the API is also a rollback of the compiler, and the builder
documents do not move with it.** A graph an author saved under the newer build
may not parse or may not compile under the older one; the boot sweep skips such a
row and logs it, so the outcome is one graph that is not launchable until the
roll-forward, not a service that will not start. That is the same skip described
in step 5, arriving from the other direction.
