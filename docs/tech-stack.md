# Tech Stack

The single place that answers "what version of X does this project use, and who
says so." Every figure below was produced by running a command on this machine,
and every command is printed next to its answer — because the command is the
contract, not the figure.

**Re-measured 2026-09-02 at `main` = `b4ef654`** (the merge of PR #6,
`6d2743c`, which brought in the flow builder), clean tree, on Windows 11 /
Python 3.13.5. Every version row in §2, §3 and §4 was re-measured this pass and
every one still holds — no lock drift, no package moved. §6's count did not
hold, and §8 has closed three findings, withdrawn a fourth and gained a new one.

The previous stamp was **2026-08-31, a five-agent read-only audit at HEAD
`c63aca0`** (branch `feat/crew-fidelity-ux`). `git rev-list c63aca0..b4ef654
--count` answers **12** — the flow-builder branch and its merge included.

> **Read this before quoting anything here.** A version number in a document is
> a claim about a moment. Three of the numbers in this repository's docs were
> wrong by 20% or more when this file was first written, not because anyone was
> careless but because the tree moved and the prose did not. Re-run the command
> in the right-hand column before you rely on a value in the left.

---

## 1. How to regenerate every figure in this file

```powershell
# Python interpreter and packages. NOTE: .venv has no pip - see §7.
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import importlib.metadata as m; print(sorted((d.metadata['Name'], d.version) for d in m.distributions()))"

# Suites - both are no-cost and fully mocked
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
Push-Location frontend; npm test; npx vue-tsc -b --force; npm run build; Pop-Location

# Node toolchain
node --version; npm --version

# Frontend resolved versions
Push-Location frontend; npm ls --depth=0; Pop-Location

# Environment knobs - MUST be a multiline scan, see §6
.\.venv\Scripts\python.exe -c "import re,pathlib;pat=re.compile(r'(?:os\.getenv|os\.environ\.get|_env_[a-z_]+)\(\s*\"([A-Z_][A-Z0-9_]*)\"',re.S);print(sorted({n for f in ('src/brief_crew/config.py','src/brief_crew/service/app.py') for n in pat.findall(pathlib.Path(f).read_text(encoding='utf-8'))}))"

# Playwright. NEEDS ITS OWN BACKEND, and needs the delay knob - see §7, quirk 6
$env:SYNTHETIC = "1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS = "5"; $env:PORT = "8099"
.\.venv\Scripts\serve.exe
Push-Location frontend; npx playwright test; Pop-Location   # second shell
```

**This file carries no test count on purpose.** The suites move faster than any
prose about them, and CLAUDE.md's *Verified Baseline* owns those figures - copy
one here and the two drift, which is the mistake §6 has made with a different
number over six published figures, five of them wrong (the tally is §6's, and
is stated once, there). Both suites and both build steps were run on 2026-09-02 at
`b4ef654` and all four were green; the counts they printed belong in CLAUDE.md.

---

## 2. Runtime

Python is pinned on **six** surfaces and they all agree. This is deliberate and
worth preserving: Render began defaulting new services to 3.14 in February 2026,
and `crewai` declares `requires-python <3.14`, so an unpinned surface is a build
failure waiting for the next service to be created.

| Surface | Value | File |
| --- | --- | --- |
| Version file | `3.13` | `.python-version:1` |
| Project metadata | `>=3.10,<3.14` | `pyproject.toml:13` |
| Lockfile | `>=3.10, <3.14` | `uv.lock:3` |
| Installed interpreter | **3.13.5** (main, Jul 1 2025) | `.venv` |
| Container | `python:3.13-slim-bookworm` (both stages) | `Dockerfile:17,42` |
| CI | `3.13` via `actions/setup-python@v5` | `.github/workflows/ci.yml:52-54` |
| Render API | `PYTHON_VERSION: "3.13"` | `render.yaml:80-81` |

**Node is now pinned on two surfaces.** §8 finding 2 - the build that ships
pinning nothing - was fixed on 2026-08-31 and is verified fixed at `b4ef654`.

| Surface | Value | File |
| --- | --- | --- |
| Local | **v24.19.0** / npm 11.17.0 | `node --version`, `npm --version` |
| CI | `24` via `actions/setup-node@v4` | `.github/workflows/ci.yml:96-98` |
| Render static site | **`NODE_VERSION: "24"`** | `render.yaml:286-287` |
| `engines` field | **still absent** | `frontend/package.json` |
| `.nvmrc` / `.node-version` | **still do not exist** | — |

The last two rows are the residual: the pin lives in a Render env var and in a
CI workflow, so a contributor's local Node is governed by nothing, and the two
pins must be kept in step by hand. `render.yaml:277-285` says so at the site.

---

## 3. Backend packages

Declared in `pyproject.toml`, resolved in `uv.lock`, installed in `.venv`. **All
three agree on every row** — there is no lock drift.

| Package | Declared | Locked = installed |
| --- | --- | --- |
| `crewai[tools]` | `>=1.15.18,<2.0.0` | **1.15.18** |
| `crewai-tools` | (via the `tools` extra, lockstep) | 1.15.18 |
| `firecrawl-py` | `>=4.40.0` | 4.40.0 |
| `pinecone` | `>=9.1.0` | 9.1.0 |
| `cohere` | `>=7.1.0` | 7.1.0 |
| `requests` | `>=2.32.0` | 2.34.2 |
| `python-dotenv` | `>=1.0.0` | 1.2.3 |
| `fastapi` (extra: `service`) | `>=0.115.0` | 0.141.1 |
| `uvicorn` (extra: `service`) | `>=0.32.0` | 0.52.4 |
| `sqlalchemy` (extra: `service`) | `>=2.0.0` | 2.0.52 |
| `pyjwt[crypto]` (extra: `service`) | `>=2.10.0` | **2.13.0** |
| `cryptography` (via the `crypto` extra) | transitive | 50.0.1 |
| `psycopg[binary]` (extra: `service`) | `>=3.2.0` | 3.3.4 |
| `starlette` | (transitive, via fastapi) | 1.6.0 |
| `pydantic` | `>=2.12,<3` (declared 2026-08-31) | 2.12.5 |
| `pyyaml` | `>=6` (declared 2026-08-31) | 6.0.3 |
| `openai` | (transitive; CrewAI's OpenAI-compatible HTTP client) | 2.54.0 |
| `litellm` | **must never be installed** — see §5 | *absent* |
| `pytest` | configured but **not installed**, not even locked | *absent* |

`crewai`, `crewai-tools`, `crewai-core` and `crewai-cli` are all **1.15.18** and
move in lockstep. `psycopg` has no `import psycopg` anywhere — it is reached
through the SQLAlchemy dialect string `postgresql+psycopg://`
(`service/app.py`), which resolves the driver lazily. That is correct usage, not
a dead dependency; a naive import-grep will misclassify it.

**Console scripts** (`pyproject.toml:55-62`), all five present in
`.venv/Scripts/`: `run_crew`, `kickoff`, `plot`, `validate`, `serve`.
`crewai.exe` is also present — it belongs to the `crewai-cli` distribution, not
to this project.

### The flow builder added no backend package

`src/brief_crew/builder/` is nine modules and 4,964 lines (`bounds`, `budget`,
`compiler`, `descriptor`, `document`, `gates`, `runtime`, `store`, plus
`__init__`), and `service/builder_api.py`, `service/builder_runner.py` and
`service/builder_rehydrate.py` are 1,208 more. Between them they import
**crewai, pydantic, sqlalchemy and yaml, and nothing else third-party** - four
rows this table already carried. `pyproject.toml` and `uv.lock` are byte-identical
across the merge.

```bash
git diff --stat 4d70cbf..b4ef654 -- pyproject.toml uv.lock   # empty
grep -rhE '^(from|import) ' src/brief_crew/builder/*.py src/brief_crew/service/builder_*.py \
  | grep -vE 'from \.|from brief_crew|from __future__' | sort -u
```

That is worth stating rather than assuming: a graph compiler that emits
`crewai.flow/v1` declarations is exactly the shape of feature that arrives with
a YAML library, a JSON-schema validator and a template engine attached. It did
not. `wc -l` and the import scan above are how to check it again, and both are
cheap.

---

## 4. Frontend packages

`package-lock.json` (`lockfileVersion: 3`) is the only lockfile. package.json →
lockfile → `node_modules` **agree on every row**, and `npm ls --depth=0` reports
no unmet peers, no invalid entries and no duplicate `vue` or `vite` copies.

| Package | Specifier | Installed |
| --- | --- | --- |
| `vue` | `^3.5.41` | **3.5.42** |
| `better-auth` | `^1.7.2` | 1.7.2 |
| `hono` | `^4.13.5` | 4.13.5 |
| `@hono/node-server` | `^2.1.1` | 2.1.1 |
| `pg` | `^8.23.0` | 8.23.0 |
| `better-sqlite3` | `^12.11.1` | 12.11.1 |
| `dotenv` | `^17.4.2` | 17.4.2 |
| `@vue-flow/core` | `^1.48.2` | 1.48.2 |
| `@vue-flow/background` | `^1.3.2` | 1.3.2 |
| `@vue-flow/controls` | `^1.1.3` | 1.1.3 |
| `lucide-vue-next` | `^1.0.0` | 1.0.0 |
| `vite` | `^8.2.2` | 8.2.2 |
| `typescript` | `~6.0.2` | **6.0.3** |
| `vue-tsc` | `^3.3.11` | 3.3.11 |
| `vitest` | `^4.1.11` | 4.1.11 |
| `jsdom` | `^30.0.1` | 30.0.1 |
| `@playwright/test` | `^1.62.1` | 1.62.1 |
| `@vitejs/plugin-vue` | `^6.0.8` | 6.0.8 |
| `@vue/test-utils` | `^2.5.0` | 2.5.0 |
| `@vue/tsconfig` | `^0.9.1` | 0.9.1 |
| `@types/node` | `^24.13.3` | 24.13.3 |

**Eleven runtime dependencies, and six of them are the auth server's.**
`node -e "console.log(Object.keys(require('./package.json').dependencies))"`,
run 2026-09-02, answers eleven: `vue`, the three `@vue-flow/*` packages and
`lucide-vue-next` are the SPA's five; `better-auth`, `hono`, `@hono/node-server`,
`pg`, `better-sqlite3` and `dotenv` are the six the Node auth service brought
with it (§13 of CLAUDE.md). This paragraph said **five** until 2026-09-02, and
it was already wrong when it was written on 2026-08-31 - the auth packages are
in the table directly above it. The prose was counting the decision the next
paragraph describes; the field it named had moved.

**The decision itself stands.** A proposal to add `marked` + `dompurify` was
declined in favour of the ~240-line renderer in `src/utils/markdown.ts`, because
the input is Reporter-agent output — untrusted by construction — and
escape-before-parse is easier to prove correct than sanitise-after-parse. Adding
a *twelfth* runtime dependency should clear the same bar.

### The flow builder added no npm package, and no design token

Two measurements, both cheap to repeat, both taken 2026-09-02:

```bash
git diff --stat 4d70cbf..b4ef654 -- frontend/package.json frontend/package-lock.json
git diff --stat 4d70cbf..b4ef654 -- frontend/src/assets/styles/tokens.css
```

Both are **empty**. The builder ships 33 `.vue` components under
`src/components/builder/`, seven `useBuilder*.ts` composables, `types/builder.ts`
(638 lines), `services/builderApi.ts` (350), six new `src/data/` modules
(`builderDefaults`, `builderRunHandoff`, `builderTemplates`,
`builderVocabulary`, `nodeKinds`, and `templates/ideaValidator`) and two new
global stylesheets - and it added nothing to `package.json` and nothing to the
64-token palette in `assets/styles/tokens.css`. The component figure is
`git diff --name-only 4d70cbf..b4ef654 -- frontend/src/components/builder`,
which reports 34 files: 33 `.vue` and one `.ts`.

Two things carried that. The canvas is `@vue-flow/core`, which the run console
already used, so the builder is a second tenancy of a dependency rather than a
second graph library. And the `#/build` route is a hand-rolled hash router
(`composables/useWorkspaceRoute.ts`, 108 lines) rather than `vue-router` -
`grep -c vue-router frontend/package.json` answers **0**.

**One honest correction to "no new custom properties".** `assets/styles/`
gained two new global stylesheets, `builder.css` (880 lines) and `node-card.css`
(281), and between them they declare one custom property that did not exist
anywhere before: `--node-shadow-color`. It is not a design token - it is a
second per-card channel of exactly the kind `--node-gradient` already was, set
by the kind-tenancy block and read by the hover rule beside it, and
`builder.css:20-27` says so itself under the heading *ZERO NEW CUSTOM
PROPERTIES*. Every colour in both files is a `tokens.css` value or a
`color-mix(in srgb, var(--token) N%, transparent)` wash. So: no new tokens, one
new local channel, and the file that introduced it flagged it first.

**Always `npx vue-tsc -b --force` before trusting a green build.** `-b` is
incremental and type-checks `tests/` as well as `src/`; a warm `.tsbuildinfo`
can skip a newly added file so it passes locally and fails on Render. This has
broken a deploy twice. Note that `npm run build` itself runs the bare `-b`
form — the `--force` is a verification step you perform, not something the
script does for you.

---

## 5. Models and external APIs

**OpenRouter is the only LLM provider.** The service asserts this at startup:
any agent LLM whose model string lacks the `openrouter/` prefix is rejected
(`service/app.py`).

| Constant | Value | Price (prompt / completion, per M) |
| --- | --- | --- |
| `CHEAP_MODEL` | `openrouter/google/gemini-3.5-flash-lite:nitro` | $0.30 / $2.50 |
| `ESCALATION_MODEL` | `openrouter/google/gemini-3.8-flash` | $0.75 / $3.75 |
| `EMBED_MODEL` | `google/gemini-embedding-2`, 768 dims | not in `PRICES` |
| `RERANK_MODEL` | `rerank-v4.0-fast` (Cohere) | not in `PRICES` |

> **Both model rows were corrected on 2026-09-04, and every price was
> re-measured with `mcp__openrouter__get-model` rather than carried across.**
>
> - `ESCALATION_MODEL` moved `gemini-3.7-flash` → **`gemini-3.8-flash`**
>   (`f19a2c6`; `src/brief_crew/config.py` carries the reasoning). Identical
>   $0.75 / $3.75, identical 1,048,576 context, higher on all three Artificial
>   Analysis indices (58.7 / 76.3 / 50.0 against 56.0 / 76.1 / 45.1).
> - `CHEAP_MODEL` had been **stale by a whole model**: this row read
>   `z-ai/glm-5.3-flash` at $0.075 / $0.250, while `config.py:49` has read
>   `openrouter/google/gemini-3.5-flash-lite:nitro` for some time. Measured
>   live: **$0.30 / $2.50**, 1,048,576 context, AA 37.4 / 49.3 / 27.2.
>
> ⚠️ **`:nitro` routes on speed, not price**, so $0.30 / $2.50 is a *published
> floor* and the effective rate can be higher — `config.py:44-47` says the same,
> and §9 below measures the spread across the endpoints that serve this slug.
> The half-price `:batch` variant ($0.15 / $1.25) is not usable here: batch is a
> queued lane, and a run with streaming frames and a human at a gate cannot be
> queued.
>
> **Consequence worth carrying:** the two tiers are **2.5× apart on prompt and
> 1.5× on completion**, not the 10× / 15× the `agents/` specifications were
> written against, and their context windows are now **equal**. Documents that
> reason from the old gap are flagged where they sit; none of those arguments
> has been re-made.

All four live in `src/brief_crew/config.py` and **nowhere else** — a targeted
grep for `openrouter/`, model-id literals and price literals across `src/`
returns nothing outside that file, and neither `agents.yaml` declares an `llm:`
key. Tiers are assigned in Python: Scoper / Synthesist / Reporter get
escalation, the three research analysts get cheap.

Embedding and rerank spend is **unaccounted** — neither model has a `PRICES`
row, so `cost_usd` covers agent LLM calls only.

**Swapping a model means editing `PRICES` in the same commit.** The table is
keyed by the constants, so they re-key themselves while the *rates* stay
attached to the old model. `compute_cost_usd` returns `None` — never `0.0` —
for an unpriced model, which is the safety net that makes the mistake visible
instead of silently free. `_build_price_index()` stores both the prefixed and
de-prefixed spelling because CrewAI's `LLM.__new__` strips the provider prefix
for native providers; without that, every call looks unpriced.

**Never install `crewai[litellm]`.** OpenRouter is a native provider in
1.15.18; litellm is only a fallback for providers absent from
`SUPPORTED_NATIVE_PROVIDERS`. Verified absent from `.venv`. CrewAI declares it
`Provides-Extra` only, so `crewai[tools]` does not pull it in.

**No `OPENAI_API_KEY` is required anywhere.** The `openai` package is present
only as CrewAI's OpenAI-compatible HTTP client, pointed at
`https://openrouter.ai/api/v1`. There is no `import openai` in `src/`.

### External API versions the code targets

| Service | Version / endpoint | File |
| --- | --- | --- |
| Firecrawl | **v2** — `Firecrawl(...).search` binds to the v2 client | `tools/market_research.py` |
| HN Algolia | v1 — `https://hn.algolia.com/api/v1/search` | `tools/hn_sentiment.py` |
| GitHub | `X-GitHub-Api-Version: 2022-11-28`, `Accept: application/vnd.github+json` | `tools/github_feasibility.py` |
| Cohere | **v2** — `ClientV2(...).rerank` resolves to `V2Client.rerank` via MRO | `tools/pinecone_retrieval.py` |
| Pinecone | modern class API `Pinecone(api_key=...)`, never `pinecone.init()` | `indexing.py`, `tools/pinecone_retrieval.py` |
| OpenRouter embeddings | `https://openrouter.ai/api/v1/embeddings` | `config.py` |

Pydantic is **v2 throughout** — `ConfigDict`, `field_validator`,
`model_validator`, `model_validate`. No `@validator`, `class Config:`, `.dict()`
or `.parse_raw()` survives anywhere in `src/`. One helper is *named*
`parse_raw_model` (`validator_guardrails.py`) but its body is `json.loads` then
`model_validate` — v2 idiom under a v1-sounding name. Do not "fix" it.

---

## 6. Environment knobs — there are forty-one

Regenerated with the multiline scan in §1 on **2026-09-03**, at
`gauntlet/plans` = `ca43ba8` (the Stage 1 contract commit `52a954f` plus one
doc commit; `main` was still `25634c0`). **Thirty-seven** are read in
`config.py` and **four** in `service/app.py` (`DATABASE_URL`, `HOST`, `PORT`,
`SYNTHETIC`). That split is itself scan output, not arithmetic on the list
below:

```powershell
.\.venv\Scripts\python.exe -c "import re,pathlib;pat=re.compile(r'(?:os\.getenv|os\.environ\.get|_env_[a-z_]+)\(\s*\"([A-Z_][A-Z0-9_]*)\"',re.S);[print(f,len(set(pat.findall(pathlib.Path(f).read_text(encoding='utf-8'))))) for f in ('src/brief_crew/config.py','src/brief_crew/service/app.py')]"
```

The block below is pasted scan output, not prose. Regenerate before trusting it.

```text
AUTH_BASE_URL                         AUTH_JWKS_CACHE_SECONDS
AUTH_JWKS_TIMEOUT_SECONDS             AUTH_JWT_LEEWAY_SECONDS
BUILDER_ALLOW_GATELESS_GRAPHS         BUILDER_REHYDRATE_PUBLISHED
CORS_ALLOW_ORIGINS                    CREDENTIALS_MASTER_KEY
DATABASE_URL                          EXPOSE_API_DOCS
HOST                                  MAX_QUEUED_RUNS
MAX_RUN_COST_USD                      PINECONE_INDEX_NAME
PORT                                  RUN_CONCURRENCY
RUN_RATE_LIMIT_MAX_RUNS               RUN_RATE_LIMIT_TRUST_FORWARDED_FOR
RUN_RATE_LIMIT_WINDOW_SECONDS         RUN_SUBMIT_SETTLE_TIMEOUT_SECONDS
SYNTHETIC                             VALIDATOR_ALLOW_AUTO_GATES
VALIDATOR_BRANCH_MAX_ITER             VALIDATOR_BRANCH_MAX_TOKENS
VALIDATOR_BRANCH_TEMPERATURE          VALIDATOR_FEASIBILITY_CACHE_ENABLED
VALIDATOR_FIRECRAWL_MAX_AGE_MS        VALIDATOR_FIRECRAWL_MAX_RETRIES
VALIDATOR_FIRECRAWL_SCRAPE_TIMEOUT_MS VALIDATOR_FIRECRAWL_TIMEOUT_SECONDS
VALIDATOR_MARKET_SEARCH_LIMIT         VALIDATOR_MAX_BRANCH_QUERIES
VALIDATOR_MAX_CLAIM_CHARS             VALIDATOR_MAX_EVIDENCE_CLAIM_CHARS
VALIDATOR_MAX_GATE_TURNS              VALIDATOR_ORPHAN_RUN_GRACE_SECONDS
VALIDATOR_ORPHAN_RUN_RECOVERY         VALIDATOR_REQUIRE_AUTH
VALIDATOR_RUN_RETENTION_DAYS          VALIDATOR_SENTIMENT_STORY_LIMIT
VALIDATOR_SEQUENTIAL_BRANCHES
```

### The two that are new since the thirty-nine

Both landed in one commit, `52a954f`, the Integrator's Stage 1 contract
commit for the gauntlet build (`.agent/plans/00-architecture.md`, S1 ruling
3), whose message said the scan now answers 41 and that this section would be
regenerated at integration rather than in the same commit. This is that
regeneration.

| Knob | Default | Landed | What it decides |
| --- | --- | --- | --- |
| `CREDENTIALS_MASTER_KEY` | `""` | `52a954f` | The AES-256-GCM master key for the per-user credential vault (plan 01, contract C4), base64 of 32 bytes, read once in `config.py` and nowhere else. It is the same fail-loud shape as `VALIDATOR_REQUIRE_AUTH`: **auth on and no key refuses to start**, because a half-configured vault is the quiet failure; auth off and no key means "no vault" and the credential routes answer 503 while everything else keeps working, which is what keeps tests, `SYNTHETIC` mode and a bare checkout runnable. `render.yaml` does not set it yet; the deployed API therefore has no vault until it does. |
| `VALIDATOR_RUN_RETENTION_DAYS` | `0` | `52a954f` | The durable half of run retention (plan 15 D7). `VALIDATOR_RUN_RETENTION_SECONDS` only ever evicted the in-memory ring, so terminal runs, their frames, metrics and gates accumulated in the database forever (CLAUDE.md closed item 32). Terminal runs older than this many days are deleted by the same periodic sweep the orphan recovery uses, and the child tables follow by `ON DELETE CASCADE`; documents, versions and credentials are never purged. `0` means keep everything, which is the deployed behaviour today and stays the default until PLANS.md decision 23 is answered; it is read with `minimum=0` because zero is the meaningful off value, not a mistake. |

### The three that were new since the thirty-six

| Knob | Default | Landed | What it decides |
| --- | --- | --- | --- |
| `AUTH_JWKS_TIMEOUT_SECONDS` | `45` | `5087f3c` | How long the API waits for Better Auth's JWKS document. It was hardcoded at 10s, and `AUTH_BASE_URL` is the studio's own Node service on Render's **free** plan, so it sleeps - timed at 2.12s warm and **40s cold**. (That timing is the change author's, recorded at `config.py:2280`; this pass did not repeat it.) A JWKS fetch that times out on a process that has never fetched any leaves it with no keys, so every bearer token is rejected and a correctly signed-in operator is told to sign in. The failure reads as a credential problem and is a cold start. |
| `BUILDER_ALLOW_GATELESS_GRAPHS` | `False` | `6d2743c` | Whether a builder graph with **no human gate** may be launched anonymously, read exactly the way `service/app.py` already reads `VALIDATOR_ALLOW_AUTO_GATES`. Off by default for the same cost reason: with it off, an anonymous author must keep a gate reachable before the first billable node, so an unanswered run stops after at most one model call. Unlike `VALIDATOR_REQUIRE_AUTH` it is a flat `False` rather than a value derived from `AUTH_BASE_URL`, because it binds only the anonymous case - wherever auth is on, `user` is always truthy and this flag is irrelevant. |
| `BUILDER_REHYDRATE_PUBLISHED` | `True` | `6d2743c` | Whether a booting process re-registers every **published** builder graph from the document store. A publish writes to six process-local registration sites (the five `register_builder_workflow` touches, plus the app's own runtime map in `builder_api._register_runtime` — the counts differ by scope, and each site names which it means); the documents are not process-local, and both Render services carry `autoDeploy: yes` - so before this existed, every push to `main` silently unpublished every user graph while the row and the canvas both still said `published`. Same shape as the orphaned runs of CLAUDE.md item 32: durable state and process state disagreeing across a restart, with only the process state consulted. The switch exists for the one case where re-registering is the wrong move - a graph that compiles and then wedges or bankrupts the deployment - as a deploy-time flip rather than a code edit or a `DELETE` against somebody's document. |

`MAX_RUN_COST_USD` is **not** among them, and saying so is not pedantry - it is
the newest way to get this number wrong. The handoff into this pass named it as
one of the three new knobs. It is not: it landed in `1b79197`, this list already
carried it on 2026-09-01, and `git log -S MAX_RUN_COST_USD` returns `6d2743c`
only because the builder commit *changed an existing reference* to it.
**Reasoning about what a commit added is not regenerating the list.** The real
third entry, `AUTH_JWKS_TIMEOUT_SECONDS`, is not builder work at all - it landed
in `5087f3c`, which means this count was already wrong at **thirty-seven**
before the builder was merged: `git rev-list 5087f3c..b4ef654 --count` answers
**5**, and nobody looked at any of them.

The Node auth service reads five of its own, none of which appear above because
they are read in TypeScript rather than in `config.py`: `BETTER_AUTH_URL`,
`BETTER_AUTH_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and
`AUTH_SKIP_MIGRATIONS`, plus `DATABASE_URL` / `AUTH_SQLITE_PATH` / `PORT` /
`HOST` / `NODE_ENV` shared with the platform. See
[`google-oauth.md`](google-oauth.md).

### The scan reads exactly two files, and that is now the hole

`config.py` and `service/app.py`. **Five more environment variables are read
elsewhere in `src/`, and not one of them is in the forty-one.** Measured
2026-09-02 by widening the same pattern over `src/**/*.py`:

```text
src/brief_crew/embeddings.py                OPENROUTER_API_KEY
src/brief_crew/service/runner.py            SYNTHETIC_BRANCH_DELAY_SECONDS
src/brief_crew/tools/github_feasibility.py  GITHUB_TOKEN
src/brief_crew/tools/market_research.py     FIRECRAWL_API_KEY
src/brief_crew/validator_cache.py           VALIDATOR_CACHE_NAMESPACE
```

Three are credentials and belong in `.env`, not in a knob list. Two are not.
`VALIDATOR_CACHE_NAMESPACE` and `SYNTHETIC_BRANCH_DELAY_SECONDS` are behavioural
switches this section has never listed, and the second is the sharper case:
**the Playwright suite does not pass without it** (§7, quirk 6). The canonical
scan is blind to a knob the test instructions require.

Widening the scan's file list is the obvious fix and it is **deliberately not
applied here.** The two-file scope is quoted verbatim in §1, in CLAUDE.md and in
the handoff to this pass; silently changing what a command means is how a count
drifts without anyone ever publishing a wrong digit. It is recorded as a defect
instead - §8, finding 7 - so that the widening happens once, everywhere, in a
commit that says it did.

> **WARNING: forty-one is the SEVENTH figure published in this section, and
> every one of the six before it went stale.** In order: *eleven*, *fifteen*,
> *eighteen*, *twenty*, *thirty-six*, *thirty-nine*. The last two were right
> when published and stale within a commit; thirty-nine lasted exactly one,
> `52a954f`. The difference this time is that the commit which added the two
> knobs said so in its message and named the regeneration as owed, which is
> the first time the count has moved in a commit that announced it would. Only the first has a technical excuse - a
> line-anchored `grep -oE 'os.getenv("[A-Z_]+"'` missed four calls the formatter
> had wrapped onto the next line, which is why §1's scan is `re.S`-multiline
> and why [gotchas](gotchas-and-insights.md) 6 exists.
>
> **Every failure since has had the same cause, and it is not the regex.** Knobs
> land in a commit that does not touch the docs. `MAX_RUN_COST_USD` and
> `VALIDATOR_MAX_GATE_TURNS` arrived in `1b79197` and went undocumented until
> the 2026-08-31 audit; `AUTH_JWKS_TIMEOUT_SECONDS` arrived in `5087f3c` and
> went undocumented until this one. The previous version of this box said the
> count had been wrong *four* times while CLAUDE.md said *five* - two documents
> narrating the same history, disagreeing about it, and neither of them
> regenerated. That is the failure in miniature.
>
> **There is no fix in this file for that**, and pretending otherwise is how the
> next figure gets published wrong. The fix is a check that runs: the scan wired
> into CI against a committed expected list, so a knob added without a doc edit
> fails a job instead of aging quietly into the next audit. It does not exist.
> Until it does - **always regenerate with the multiline scan; never with a
> line-anchored grep, never by reading this list, and never by reasoning about
> what a commit added.**

Everything else in the admission path is a genuine constant with no override:
`MAX_REQUEST_BODY_BYTES` (64 KiB), `MAX_RUN_INPUT_CHARS` (2000),
`MAX_RUN_INPUT_BYTES` (8 KiB), `MAX_RUN_INPUT_KEYS` (16),
`MAX_RUN_RESULT_BODY_CHARS` (64 KiB), `RUN_ADMISSION_RETRY_AFTER_SECONDS` (30),
`RUN_RATE_LIMIT_MAX_CLIENTS` (4096), `RUN_RATE_LIMIT_KEY_MAX_CHARS` (64), and
the `RESERVED_RUN_INPUT_KEYS` set. The builder's structural ceilings
(`MAX_BILLABLE_NODES` 13, `MAX_ESCALATION_NODES` 8, `MAX_CYCLES` 3,
`MAX_FANOUT_WIDTH` 4 - `config.py:1800`, `:1809`, `:1845`, `:1828`) are constants of the same kind - they take no environment override at
all, which is why none of them appears above and why raising three of them was
a code change rather than a deploy-time flip.

`render.yaml` sets **none** of the admission knobs and **neither `BUILDER_*`
knob**, so production runs on the defaults: no anonymous gateless graphs, and
published graphs rehydrated at boot. One knob still needs a decision anywhere
other than Render: `RUN_RATE_LIMIT_TRUST_FORWARDED_FOR` defaults **on**, which
is right behind a proxy and wrong for a directly-reachable host, where
`X-Forwarded-For` is attacker-supplied and the limiter stops limiting.

---

## 7. Toolchain quirks that will waste your time

1. **`.venv` has no `pip`.** It was built by `uv`, which does not seed pip.
   `python -m pip ...` fails with `No module named pip`. Read versions from
   `importlib.metadata` or `.venv/Lib/site-packages/*.dist-info` instead. Any
   instruction anywhere telling you to `pip install` does not work here.
2. **`pytest` is configured but absent.** `[tool.pytest.ini_options]` in
   `pyproject.toml` is inert — pytest is not installed and not even in
   `uv.lock`. The suite is `unittest`, and so is CI.
3. **`unittest discover` walks silently past a directory with no
   `__init__.py`.** This once hid `tests/events/` and `tests/service/` entirely
   behind a green `OK`. Add the `__init__.py` in the same commit as any new
   test directory. `tests/builder/` has one; that is not luck, it is this entry.
4. **`uv` is not one version.** The system CLI is 0.7.19, `Dockerfile:20` pins
   `ghcr.io/astral-sh/uv:0.7.19`, CI's `astral-sh/setup-uv@v5` pins nothing, and
   `uv.lock` separately locks a `uv==0.11.33` *Python package* pulled in by
   `crewai-cli`. These are four different things; do not quote "the uv version".
5. **The default Vite dev server proxies to the paid backend.** `vite.config.ts`
   points `/api` and `/ws` at `127.0.0.1:8000`. The free one is
   `e2e/vite.e2e.config.ts` → `127.0.0.1:8099` with `SYNTHETIC=1`.
6. **Playwright needs `SYNTHETIC_BRANCH_DELAY_SECONDS=5` on the backend, and
   its absence reads as a CSS regression.** Three of the specs in
   `e2e/visual/run-canvas.spec.ts` screenshot a node *while a research branch is
   in flight*. The synthetic runner finishes a branch instantly, so with the
   knob unset there is no running moment to capture and the specs fail with
   `No branch stayed in flight` (`run-canvas.spec.ts:211`) — which looks exactly
   like the running-state styling having broken, and is not.

   ```powershell
   $env:SYNTHETIC = "1"; $env:SYNTHETIC_BRANCH_DELAY_SECONDS = "5"; $env:PORT = "8099"
   .\.venv\Scripts\serve.exe
   ```

   Two things make this trap sharp. The knob is read in
   `service/runner.py:65` — **not** in `config.py` or `service/app.py`, so §6's
   canonical scan cannot see it and no knob list in this repository has ever
   named it. And the suite's dependency on it is documented only in the spec's
   own docblock (`run-canvas.spec.ts:37-40`) and in the assertion message, both
   of which you reach *after* the failure rather than before it. Kill the
   backend with `Stop-Process -Name serve -Force`, never `pkill` — see
   [gotchas](gotchas-and-insights.md) 25.

---

## 8. Stack-hygiene defects

Findings 1-3 were raised by the 2026-08-31 audit and are **verified fixed at
`b4ef654`**; finding 4 was **withdrawn** — the audit misread it. Findings 5 and
6 are still open and were re-checked this pass. Finding 7 is new.

**Every one of these is invisible to a green test run** — the suite passes, CI
passes, the deploy serves. Each is a case where something holds *by accident*
rather than by declaration, which is why a version audit cannot be done by
running tests.

1. ~~**[High] `pydantic` and `PyYAML` are direct imports that nothing
   declares.**~~ **FIXED.** `pyproject.toml` now declares `pydantic>=2.12,<3`
   and `pyyaml>=6`, each with a comment naming where it is imported and why it
   was missed. Verified 2026-09-02 by reading the `dependencies` array.

   The reason it was invisible is the part worth keeping. `pyproject.toml`
   already carried *"Must be named explicitly - crewai[tools] does not pull it
   in"* for `firecrawl-py`: somebody had reasoned about this exact hazard and
   fixed the case they noticed. Pydantic was missed *because* CrewAI does pull
   it in — the dependency is only hidden while it works, and the failure when
   the luck runs out is a v1/v2 API mismatch far from its cause.
2. ~~**[High] Render's static-site build pins no Node version.**~~ **FIXED.**
   `render.yaml:286-287` sets `NODE_VERSION: "24"`, matching CI, with a comment
   at `:277-285` saying to keep the two in step. `vite@8` requires
   `^20.19.0 || >=22.12.0`, so the floor is real and a platform default drifting
   below it fails the deploy rather than the tests. Residual, recorded in §2:
   there is still no `engines.node` and no `.nvmrc`, so a contributor's local
   Node is governed by nothing.
3. ~~**[Medium] `frontend/e2e/` is type-checked by nothing.**~~ **FIXED.**
   `frontend/tsconfig.json` `references` now lists five projects, `./e2e` among
   them (and `./tsconfig.server.json`, which the auth work added). Verified
   2026-09-02 by reading the file; `npx vue-tsc -b --force` exits 0 across all
   five.

   The original fix was proved by *breaking* it — a deliberate
   `const x: number = "not a number"` in `studio.spec.ts` produced
   `TS2322` and was reverted — and that method is the entry. Without it, "fixed"
   is indistinguishable from the previous state, because `tsc -b` builds a graph
   and an unreferenced config is simply not in it: no warning, no orphan
   diagnostic. It looks fine in an editor because a language server resolves the
   nearest config walking up from the open file, which is a different algorithm
   from the build's.
4. ~~**[Medium] `CREWAI_TRACING_ENABLED` is inverted between the two deploy
   paths.**~~ **WITHDRAWN — the audit misread it, and no value was changed.**
   The two paths choose different *modes*: `render.yaml:152-153` sets `"true"`
   for **ephemeral** tracing (unauthenticated, short-lived links, the documented
   Render answer); `Dockerfile:50-56` sets `false` because the **authenticated**
   credential `tokens.enc` is a secret that expires and must never be baked into
   an image. Both comments now name which mode they are choosing and cross-
   reference the other, so the misreading is not available a second time.

   **One real finding fell out of checking it, and it is still live.**
   `CREWAI_TRACING_ENABLED=false` is *not* a disable switch — CrewAI's resolver
   has no branch returning `False` for it; the value fails the `("true","1")`
   test and falls through to *stored consent*. The Dockerfile's `false` reads as
   off only because a fresh container has no stored `trace_consent`. Anything
   that ships a consent file re-enables tracing with that line untouched. The
   Dockerfile says so at the site.
5. **[Low, OPEN] GitHub Actions are pinned to mutable tags**, not SHAs. Verified
   still true 2026-09-02 (`grep -nE 'uses:' .github/workflows/ci.yml`):
   `actions/checkout@v4` (twice), `actions/setup-python@v5`,
   `astral-sh/setup-uv@v5`, `actions/setup-node@v4`. Blast radius is capped
   today by `permissions: contents: read` and no secrets in the workflow. This
   becomes Medium the moment the workflow gains a deploy step or a secret.
6. **[Low, OPEN] No `LICENSE` file at the repo root** — for a public repository
   that means all rights reserved. Verified still true 2026-09-02 (`ls LICENSE*`
   finds nothing). `pyproject.toml:6-10` documents the gap in a comment, which
   is not a licence.
7. **[Medium, NEW] The canonical environment-knob scan reads two files, and
   five knobs live outside them.** §6's scan is hardcoded to `config.py` and
   `service/app.py`. Widening the same pattern over `src/**/*.py` on 2026-09-02
   found `OPENROUTER_API_KEY`, `GITHUB_TOKEN` and `FIRECRAWL_API_KEY` — fine,
   those are credentials — and two that are not: `VALIDATOR_CACHE_NAMESPACE`
   (`validator_cache.py`) and `SYNTHETIC_BRANCH_DELAY_SECONDS`
   (`service/runner.py`).

   This is the same defect class as the line-anchored grep of
   [gotchas](gotchas-and-insights.md) 6, one level up: that time the *pattern*
   under-reported, this time the *file list* does. It matters more than it
   looks, because §7 quirk 6 makes `SYNTHETIC_BRANCH_DELAY_SECONDS` a
   prerequisite for a green Playwright run — the scan is blind to a knob the
   test instructions require.

   **Fix:** widen the scan to `src/**/*.py`, in one commit, updating §1,
   §6, CLAUDE.md and any handoff that quotes the two-file form, and decide
   there whether credentials are listed or explicitly excluded. It was not done
   in this pass on purpose: the two-file scope is quoted verbatim in three
   places, and silently changing what a command means is how a count drifts
   without anyone publishing a wrong digit.

---

## 9. What this pass did not verify

Re-stated for the 2026-09-02 pass at `b4ef654`. The 2026-08-31 caveats that
still stand are repeated rather than referenced, because a caveat that has to be
chased is a caveat nobody reads.

- **Nothing was probed live.** No request was made to the deployed API, the
  static site, OpenRouter, Pinecone, Cohere, Firecrawl, GitHub or Render. Every
  deployment figure here is what the manifests *declare*, not what is running.
  That includes `NODE_VERSION: "24"` in §2: it is read out of `render.yaml`, not
  observed in a build log.
- **CI status was not checked in the 2026-09-02 doc pass, and the open question
  it left is now CLOSED.** `ci.yml` declares **two** jobs, `python` (:38) and
  `frontend` (:84) (`grep -nE '^  [a-z-]+:'`), while the handoff reported
  "4/4 jobs green" on the PR. Both are right about different things, and the
  word "jobs" is what made them look irreconcilable: `ci.yml` triggers on
  **both** `push` and `pull_request`, so the PR head `6d2743c` carried four
  *check-runs* — the same two jobs, once per trigger. Measured 2026-09-02:

  ```bash
  gh api repos/<owner>/<repo>/commits/6d2743c/check-runs --jq .total_count
  # 4
  # Python tests (no-cost)  |  Frontend type-check and build   <- run 33597650681 (pull_request)
  # Frontend type-check and build  |  Python tests (no-cost)   <- run 33597618486 (push)

  gh run view 33597756398 --json jobs --jq '.jobs[].name'
  # Frontend type-check and build
  # Python tests (no-cost)          <- 2, on main at b4ef654, push only
  ```

  A check-run count is a *job x trigger* product, so it is never the number to
  publish when the claim is about what CI does. Say "two jobs"; say "4/4 checks"
  only when quoting the tab. **This is the one bullet in §9 that has been
  discharged** — everything else below still stands as written.
- **Playwright was listed, not run.** `npx playwright test --list` reports
  **28 tests in 4 files** on 2026-09-02, which is where §7 quirk 6's spec
  references come from. No browser was launched and no backend was started, so
  the `SYNTHETIC_BRANCH_DELAY_SECONDS` failure mode in quirk 6 is transcribed
  from the spec's assertion message and docblock — **not reproduced here**.
  *Superseded 2026-09-03 on `gauntlet/plans`:* run, not listed — **34 tests
  in 5 files**, 34 green on the final run against a fresh `SYNTHETIC=1`
  backend on :8099 with the delay knob and `CREDENTIALS_MASTER_KEY` set,
  1.9m, zero console errors; two builder tests are timing-flaky at rates
  measured in CLAUDE.md remaining-work item 44. `main` is unchanged at 28.
- **The Docker image has never been built on this machine** (`Dockerfile:11-12`
  says so itself), so the two-stage `uv sync` sequence is unproven.
- **The keyless run was not repeated.** Moving `.env` aside is the one hazardous
  step in this verification — it holds seven live keys. If you do it, restore
  from a shell trap that fires on any exit, and confirm the backup filename is
  actually ignored with `git check-ignore -v` on the real path, never by reading
  `.gitignore`.
- **Model IDs are reported as literals.** No call was made to OpenRouter or
  Cohere to confirm any of the four models is still in the catalogue, and no
  price was re-read from the live catalogue this pass. CLAUDE.md's OpenRouter
  MCP section is the instrument for that, and it also records the thing §5's
  price table cannot: `:nitro` routes on speed, so a real run can bill well
  above the published floor recorded here.
- **The builder's own figures are counts of files, not of behaviour.** §3 and
  §4 report line counts, component counts and two empty `git diff --stat`s.
  They say the builder added no dependency and no token. They say nothing about
  whether it compiles a correct flow; `docs/flow-builder-spec.md` is the
  contract, and the suites are the evidence.
