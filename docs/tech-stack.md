# Tech Stack

The single place that answers "what version of X does this project use, and who
says so." Every figure below was produced by running a command on this machine,
and every command is printed next to its answer — because the command is the
contract, not the figure.

**Verified 2026-08-31 by a five-agent read-only audit at HEAD `c63aca0`**
(branch `feat/crew-fidelity-ux`, clean tree), on Windows 11 / Python 3.13.5.

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
```

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

**Node is pinned on one surface and unpinned on the one that ships.** See §8,
finding 2.

| Surface | Value | File |
| --- | --- | --- |
| Local | **v24.19.0** / npm 11.17.0 | `node --version` |
| CI | `24` via `actions/setup-node@v4` | `.github/workflows/ci.yml:96-98` |
| Render static site | **none declared** | `render.yaml` (no `NODE_VERSION`) |
| `engines` field | **absent** | `frontend/package.json` |
| `.nvmrc` / `.node-version` | **do not exist** | — |

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
| `pydantic` | ⚠️ **not declared** — see §8 finding 1 | 2.12.5 |
| `PyYAML` | ⚠️ **not declared** — see §8 finding 1 | 6.0.3 |
| `openai` | (transitive; CrewAI's OpenAI-compatible HTTP client) | 2.54.0 |
| `litellm` | **must never be installed** — see §5 | *absent* |
| `pytest` | configured but **not installed**, not even locked | *absent* |

`crewai`, `crewai-tools`, `crewai-core` and `crewai-cli` are all **1.15.18** and
move in lockstep. `psycopg` has no `import psycopg` anywhere — it is reached
through the SQLAlchemy dialect string `postgresql+psycopg://`
(`service/app.py`), which resolves the driver lazily. That is correct usage, not
a dead dependency; a naive import-grep will misclassify it.

**Console scripts** (`pyproject.toml:37-44`), all five present in
`.venv/Scripts/`: `run_crew`, `kickoff`, `plot`, `validate`, `serve`.
`crewai.exe` is also present — it belongs to the `crewai-cli` distribution, not
to this project.

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

**Exactly five runtime dependencies, and that is a decision.** A proposal to add
`marked` + `dompurify` was declined in favour of the ~240-line renderer in
`src/utils/markdown.ts`, because the input is Reporter-agent output — untrusted
by construction — and escape-before-parse is easier to prove correct than
sanitise-after-parse. Adding a sixth runtime dependency should clear the same
bar.

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
| `CHEAP_MODEL` | `openrouter/z-ai/glm-5.3-flash` | $0.075 / $0.250 |
| `ESCALATION_MODEL` | `openrouter/google/gemini-3.7-flash` | $0.75 / $3.75 |
| `EMBED_MODEL` | `google/gemini-embedding-2`, 768 dims | not in `PRICES` |
| `RERANK_MODEL` | `rerank-v4.0-fast` (Cohere) | not in `PRICES` |

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

## 6. Environment knobs — there are thirty-six

Regenerated with the multiline scan in §1 on **2026-09-01**. **Thirty-two** are
read in `config.py` and **four** in `service/app.py` (`DATABASE_URL`, `HOST`,
`PORT`, `SYNTHETIC`).

> The previous figure here was **twenty**, and it was short by sixteen. Four of
> those are the authentication knobs added on 2026-09-01; the other **twelve
> were already present and already missing from this list** — every
> `VALIDATOR_FIRECRAWL_*`, every `VALIDATOR_BRANCH_*`, the two
> `VALIDATOR_MAX_*_CHARS`, `VALIDATOR_MARKET_SEARCH_LIMIT`,
> `VALIDATOR_SENTIMENT_STORY_LIMIT` and `VALIDATOR_MAX_BRANCH_QUERIES`. This
> block is pasted scan output, not prose. Regenerate before trusting it.

```text
AUTH_BASE_URL                         AUTH_JWKS_CACHE_SECONDS
AUTH_JWT_LEEWAY_SECONDS               CORS_ALLOW_ORIGINS
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
VALIDATOR_SENTIMENT_STORY_LIMIT       VALIDATOR_SEQUENTIAL_BRANCHES
```

The Node auth service reads five of its own, none of which appear above because
they are read in TypeScript rather than in `config.py`: `BETTER_AUTH_URL`,
`BETTER_AUTH_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and
`AUTH_SKIP_MIGRATIONS`, plus `DATABASE_URL` / `AUTH_SQLITE_PATH` / `PORT` /
`HOST` / `NODE_ENV` shared with the platform. See
[`google-oauth.md`](google-oauth.md).

> **⚠️ This count has now been wrong four times, and never for the same
> reason.** It was published as *eleven* when a line-anchored
> `grep -oE 'os\.getenv\("[A-Z_]+"'` missed four calls the formatter had
> wrapped onto the next line. Then as *fifteen*, then as *eighteen*, each time
> because knobs landed in a commit that did not touch the docs —
> `MAX_RUN_COST_USD` (default `10.0`) and `VALIDATOR_MAX_GATE_TURNS`
> (default `5`) both arrived in `1b79197` and went undocumented until this
> audit. **Always regenerate with the multiline scan; never with a
> line-anchored grep, and never by reading this list.**

Everything else in the admission path is a genuine constant with no override:
`MAX_REQUEST_BODY_BYTES` (64 KiB), `MAX_RUN_INPUT_CHARS` (2000),
`MAX_RUN_INPUT_BYTES` (8 KiB), `MAX_RUN_INPUT_KEYS` (16),
`MAX_RUN_RESULT_BODY_CHARS` (64 KiB), `RUN_ADMISSION_RETRY_AFTER_SECONDS` (30),
`RUN_RATE_LIMIT_MAX_CLIENTS` (4096), `RUN_RATE_LIMIT_KEY_MAX_CHARS` (64), and
the `RESERVED_RUN_INPUT_KEYS` set.

`render.yaml` sets **none** of the admission knobs, so production runs on the
defaults. One knob needs a decision anywhere other than Render:
`RUN_RATE_LIMIT_TRUST_FORWARDED_FOR` defaults **on**, which is right behind a
proxy and wrong for a directly-reachable host, where `X-Forwarded-For` is
attacker-supplied and the limiter stops limiting.

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
   test directory.
4. **`uv` is not one version.** The system CLI is 0.7.19, `Dockerfile:20` pins
   `ghcr.io/astral-sh/uv:0.7.19`, CI's `astral-sh/setup-uv@v5` pins nothing, and
   `uv.lock` separately locks a `uv==0.11.33` *Python package* pulled in by
   `crewai-cli`. These are four different things; do not quote "the uv version".
5. **The default Vite dev server proxies to the paid backend.** `vite.config.ts`
   points `/api` and `/ws` at `127.0.0.1:8000`. The free one is
   `e2e/vite.e2e.config.ts` → `127.0.0.1:8099` with `SYNTHETIC=1`.

---

## 8. Open stack-hygiene defects

Found by the 2026-08-31 audit. **Every one is invisible to a green test run** —
the suite passes, CI passes, the deploy serves. Each is a case where something
holds *by accident* rather than by declaration.

1. **[High] `pydantic` and `PyYAML` are direct imports that nothing declares.**
   `pydantic` is imported in 15 files — the schema layer, both Flow states, and
   all of `service/`. `PyYAML` is imported at `service/app.py`. Neither appears
   anywhere in `pyproject.toml`; both resolve only because transitive
   dependencies happen to require them (13 locked packages require pydantic).
   `pyproject.toml:19` already carries *"Must be named explicitly — crewai[tools]
   does not pull it in"* for `firecrawl-py`, so the rule exists and was applied
   selectively. **Fix:** add `pydantic>=2.12,<3` and `pyyaml>=6` to
   `dependencies`.
2. **[High] Render's static-site build pins no Node version.** CI pins 24; the
   build that actually ships pins nothing, so it runs on Render's platform
   default at build time. `vite@8` requires `^20.19.0 || >=22.12.0` and
   `jsdom@30` requires `^22.22.2 || ^24.15.0 || >=26.0.0`. Same defect class as
   the `.tsbuildinfo` trap, one layer up: the build environment that ships is
   the one verified least. **Fix:** add `NODE_VERSION: "24"` to the static
   site's `envVars`, or an `engines.node` field.
3. **[Medium] `frontend/e2e/` is type-checked by nothing.**
   `e2e/tsconfig.json` exists and includes `**/*.ts` plus
   `playwright.config.ts`, but the root `tsconfig.json` `references` array lists
   only `tsconfig.app.json`, `tsconfig.node.json` and `tsconfig.vitest.json`.
   `tsc -b` builds a *graph*, and an unreferenced config is not a node in it —
   no warning, no diagnostic. Playwright transpiles without type-checking, so
   nothing catches an error in `studio.spec.ts` at all. It looks fine locally
   because a language server resolves the nearest config walking up from the
   open file, which is a different algorithm than the build uses. **Fix:** add
   `{"path": "./e2e"}` to `references`.
4. **[Medium] `CREWAI_TRACING_ENABLED` is inverted between the two deploy
   paths.** `Dockerfile:56` sets `false`, with the reason at `:50-51`:
   authenticated tracing needs `tokens.enc`, which is a secret, expires, and is
   `.dockerignore`d. `render.yaml:110` sets `"true"` — with the *same argument*
   printed directly above it. A value contradicting its own stated rationale is
   worse than a plain wrong value, because the reader checks the reasoning,
   finds it sound, and never compares it to the line below.
5. **[Low] GitHub Actions are pinned to mutable tags**, not SHAs:
   `actions/checkout@v4`, `actions/setup-python@v5`, `astral-sh/setup-uv@v5`,
   `actions/setup-node@v4`. Blast radius is capped today by
   `permissions: contents: read` and no secrets in the workflow. This becomes
   Medium the moment the workflow gains a deploy step or a secret.
6. **[Low] No `LICENSE` file at the repo root** — for a public repository that
   means all rights reserved. `pyproject.toml:6-10` documents the gap in a
   comment, which is not a licence.

---

## 9. What this audit did not verify

- **Nothing was probed live.** No request was made to the deployed API, the
  static site, OpenRouter, Pinecone, Cohere, Firecrawl, GitHub or Render. Every
  deployment figure here is what the manifests *declare*, not what is running.
- **The Docker image has never been built on this machine** (`Dockerfile:11-12`
  says so itself), so the two-stage `uv sync` sequence is unproven.
- **The keyless run was not repeated.** Moving `.env` aside is the one hazardous
  step in this verification — it holds seven live keys. If you do it, restore
  from a shell trap that fires on any exit, and confirm the backup filename is
  actually ignored with `git check-ignore -v` on the real path, never by reading
  `.gitignore`.
- **Playwright E2E was not run** — it needs a backend, and this pass started
  none. It is no-cost, but against a *synthetic* backend, so it proves the
  plumbing, not the agents.
- **Model IDs are reported as literals.** No call was made to OpenRouter or
  Cohere to confirm any of the four models is still in the catalogue.
